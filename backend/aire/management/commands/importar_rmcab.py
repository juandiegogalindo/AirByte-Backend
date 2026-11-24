import csv
import hashlib
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_slug
from django.core.exceptions import ValidationError
from django.db import transaction

from aire.inferencia import VARIABLES
from aire.models import Estacion, MedicionHoraria, VersionHistorico

BOGOTA = ZoneInfo("America/Bogota")
SHA_V1 = "47b3962edd58428384500e7a3010e85f7e86b78a32cd4e4d8f1f152cca69dad8"
IDENTIDAD = ["estacion", "fecha_hora", "archivo_origen"]


def instante_local(texto):
    for formato in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            fecha, hora = texto.strip().split(" ")
            dia = datetime.strptime(fecha, formato)
            if hora in ("24:00", "24:00:00"):
                return (dia + timedelta(days=1)).replace(tzinfo=BOGOTA)
            momento = datetime.fromisoformat(f"{dia.date()}T{hora}")
            if momento.minute or momento.second or momento.microsecond or momento.tzinfo:
                raise ValueError
            return momento.replace(tzinfo=BOGOTA)
        except ValueError:
            continue
    raise ValueError(texto)


def numero(texto, conteos):
    texto = (texto or "").strip()
    if texto.upper() in {"", "-", "----", "NA", "N/A", "NONE", "NULL"}:
        return None
    try:
        valor = float(texto.replace(",", "."))
        if math.isfinite(valor) and valor < 1000:
            return valor
    except ValueError:
        pass
    conteos["valores_descartados"] += 1
    return None


class Command(BaseCommand):
    help = "Importa un consolidado horario firmado, en su orden original."

    def add_arguments(self, parser):
        parser.add_argument("--archivo", required=True, type=Path)
        parser.add_argument("--version-datos", required=True)
        parser.add_argument("--estacion")

    @transaction.atomic
    def handle(self, *args, archivo, version_datos, estacion, **options):
        version = version_datos
        try:
            validate_slug(version)
            if len(version) > 50:
                raise ValidationError("longitud")
        except ValidationError as error:
            raise CommandError("Código de versión inválido.") from error
        estaciones = Estacion.objects.all()
        if estacion:
            estaciones = estaciones.filter(slug=estacion)
        catalogo = dict(estaciones.values_list("nombre_modelo", "id"))
        if not catalogo:
            raise CommandError("Estación desconocida o catálogo vacío.")
        if not archivo.is_file():
            raise CommandError("Archivo ausente.")
        with archivo.open("rb") as entrada:
            huella = hashlib.file_digest(entrada, "sha256").hexdigest()
        if version == "rmcab-v1" and huella != SHA_V1:
            raise CommandError("La huella no corresponde a rmcab-v1.")
        lote, _ = VersionHistorico.objects.select_for_update().get_or_create(
            codigo=version, defaults={"sha256": huella, "fuente": archivo.name})
        if huella != lote.sha256:
            raise CommandError("Esta versión ya identifica otro contenido.")
        filas = {}
        conteos = Counter()
        with archivo.open(encoding="utf-8-sig", newline="") as entrada:
            lector = csv.DictReader(entrada)
            if not set([*IDENTIDAD, *VARIABLES]).issubset(lector.fieldnames or []):
                raise CommandError("Faltan columnas en el consolidado.")
            for row in lector:
                nombre = row["estacion"]
                if nombre not in catalogo:
                    if estacion:
                        continue
                    raise CommandError(f"Estación desconocida: {nombre}")
                try:
                    hora = instante_local(row["fecha_hora"])
                except ValueError:
                    conteos["fechas_descartadas"] += 1
                    continue
                clave = (catalogo[nombre], hora)
                valores = tuple(numero(row[c], conteos) for c in VARIABLES)
                if clave in filas:
                    conteos["duplicados" if filas[clave][0] == valores else "conflictos"] += 1
                filas[clave] = (valores, row["archivo_origen"])
        if not filas:
            raise CommandError("El archivo no contiene mediciones para esta selección.")
        meses = defaultdict(Counter)
        batch = []
        campos = list(VARIABLES.values())
        def guardar():
            MedicionHoraria.objects.bulk_create(batch, batch_size=1000, update_conflicts=True,
                unique_fields=["version", "estacion", "instante"], update_fields=[*campos, "archivo_origen"])
            batch.clear()
        for (sid, hora), (valores, origen) in filas.items():
            calidad = meses[sid, hora.strftime("%Y-%m")]
            calidad["horas"] += 1
            for nombre, valor in zip(campos, valores):
                if valor is None:
                    calidad[nombre] += 1
            batch.append(MedicionHoraria(version=lote, estacion_id=sid, instante=hora,
                         archivo_origen=origen, **dict(zip(campos, valores))))
            if len(batch) == 1000:
                guardar()
        if batch:
            guardar()
        nombres = {sid: nombre for nombre, sid in catalogo.items()}
        for (sid, mes), calidad in sorted(meses.items()):
            self.stdout.write(f"{nombres[sid]} {mes}: {dict(calidad)}")
        self.stdout.write(f"{version}: {len(filas)} horas únicas. {dict(conteos)}")

