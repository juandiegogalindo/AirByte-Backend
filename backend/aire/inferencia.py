import hashlib
from functools import lru_cache
from pathlib import Path
from threading import Lock

import joblib
import pandas as pd
from django.conf import settings

VARIABLES = {
    "PM2.5": "pm25", "PM10": "pm10", "Precipitacion": "precipitacion",
    "Temperatura": "temperatura", "Vel Viento": "vel_viento", "Dir Viento": "dir_viento",
}
ESTACIONES = ("Carvajal-Sevillana", "Kennedy", "Puente Aranda", "Tunal", "Usaquen")
RETARDOS = (1, 3, 6, 24)
TIPOS = {
    **{f"{nombre}_actual": "float64" for nombre in VARIABLES},
    "hora": "int32", "mes": "int32",
    **{f"estacion_{nombre}": "bool" for nombre in ESTACIONES},
    **{f"pm25_hace_{h}h": "float64" for h in RETARDOS},
}
MODELO_SHA = "a7b830718a0a60b25d4fcdf88b8243d7a771c36ede9d05826f40c76218de0d86"
_carga = Lock()


class ModeloNoDisponible(Exception):
    pass


@lru_cache(maxsize=1)
def _cargar(ruta):
    try:
        with Path(ruta).open("rb") as archivo:
            if hashlib.file_digest(archivo, "sha256").hexdigest() != MODELO_SHA:
                raise ModeloNoDisponible("La huella del modelo no coincide.")
            archivo.seek(0)
            modelo = joblib.load(archivo)
        if list(modelo.feature_names_in_) != list(TIPOS):
            raise ModeloNoDisponible("El modelo contiene otras columnas.")
        return modelo
    except (OSError, ImportError, ValueError, AttributeError) as error:
        raise ModeloNoDisponible("No se pudo cargar el modelo.") from error


def predecir(entradas):
    with _carga:
        modelo = _cargar(settings.MODEL_PATH)
    if entradas.keys() != TIPOS.keys():
        raise ValueError("Las columnas de inferencia están incompletas.")
    fila = pd.DataFrame([entradas], columns=list(TIPOS)).astype(TIPOS)
    return float(modelo.predict(fila)[0])
