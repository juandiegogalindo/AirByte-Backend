from datetime import timedelta
from functools import lru_cache
from math import isfinite
from pathlib import Path
from unicodedata import normalize
from zoneinfo import ZoneInfo

import joblib
import pandas as pd
import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .inferencia import TIPOS
from .models import Estacion, MedicionHoraria, VersionHistorico

URL = "https://rmcab.ambientebogota.gov.co/ajax/getAllStations/"
BOGOTA = ZoneInfo("America/Bogota")
VERSION = "rmcab-actual"
MONITORES = {
    "pm25": ("pm25", {"µg/m3", "ug/m3"}),
    "pm10": ("pm10", {"µg/m3", "ug/m3"}),
    "precipitacion": ("precipitacion", {"mm"}),
    "rain": ("precipitacion", {"mm"}),
    "temperatura": ("temperatura", {"°c", "c"}),
    "temp": ("temperatura", {"°c", "c"}),
    "velviento": ("vel_viento", {"m/s"}),
    "windspd": ("vel_viento", {"m/s"}),
    "dirviento": ("dir_viento", {"°", "grados", "deg"}),
    "winddir": ("dir_viento", {"°", "grados", "deg"}),
}


def clave(texto):
    return "".join(c for c in normalize("NFKD", str(texto)).lower() if c.isascii() and c.isalnum())


def sincronizar():
    ahora = timezone.now()
    respuesta = requests.get(URL, timeout=(3, 5))
    respuesta.raise_for_status()
    datos = respuesta.json()
    if not isinstance(datos, list):
        raise ValueError("Formato de datos desconocido.")
    estaciones = {clave(e.nombre_modelo): e for e in Estacion.objects.all()}
    filas = {}
    for fuente in datos:
        estacion = estaciones.get(clave(fuente.get("name")))
        if not estacion:
            continue
        for monitor in fuente.get("monitors") or []:
            campo = MONITORES.get(clave(monitor.get("name")))
            if not campo:
                continue
            unidad = (monitor.get("unit") or "").lower().replace(" ", "").replace("³", "3").replace("μ", "µ")
            if unidad not in campo[1]:
                continue
            try:
                momento = parse_datetime(monitor.get("DateVal") or "")
                numero = float(str(monitor.get("value")).replace(",", "."))
            except (ValueError, TypeError):
                continue
            if momento is None or not isfinite(numero) or numero >= 1000:
                continue
            if momento.tzinfo is None:
                momento = momento.replace(tzinfo=BOGOTA)
            if not (ahora - timedelta(days=2) <= momento <= ahora) or momento.minute or momento.second:
                continue
            filas.setdefault((estacion.pk, momento), {})[campo[0]] = numero
    if not filas:
        raise ValueError("La RMCAB no entregó mediciones recientes compatibles.")
    with transaction.atomic():
        version, _ = VersionHistorico.objects.get_or_create(
            codigo=VERSION, defaults={"sha256": "", "fuente": URL})
        for (estacion_id, instante), campos in filas.items():
            MedicionHoraria.objects.update_or_create(version=version, estacion_id=estacion_id,
                instante=instante, defaults={**campos, "archivo_origen": URL})
    return len(filas)


def actualizar_si_corresponde():
    if not cache.add("rmcab-intento", True, 300):
        return
    try:
        sincronizar()
    except (requests.RequestException, ValueError):
        # La última lectura almacenada sigue disponible y conserva su fecha real.
        return


@lru_cache(maxsize=1)
def cargar_horario(ruta):
    paquete = joblib.load(ruta)
    modelos = paquete["modelos"]
    if set(modelos) != set(range(1, 25)) or any(list(m.feature_names_in_) != list(TIPOS) for m in modelos.values()):
        raise ValueError("El artefacto horario no coincide con las entradas.")
    return modelos


def pronosticar_24(entradas):
    ruta = Path(settings.ROOT / "modelo/air_byte_pm25_horario.joblib")
    modelos = cargar_horario(ruta)
    fila = pd.DataFrame([entradas], columns=list(TIPOS)).astype(TIPOS)
    return [(h, float(modelos[h].predict(fila)[0])) for h in range(1, 25)]
