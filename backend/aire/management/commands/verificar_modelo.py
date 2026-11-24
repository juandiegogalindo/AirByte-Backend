import json
import math

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from aire.inferencia import ModeloNoDisponible, predecir


class Command(BaseCommand):
    help = "Comprueba el artefacto con la referencia congelada de Tunal."

    def handle(self, *args, **options):
        ref = json.loads((settings.ROOT / "notebooks/prediccion_referencia.json").read_text(encoding="utf-8"))
        try:
            resultado = predecir(ref["entradas"])
        except ModeloNoDisponible as error:
            raise CommandError(str(error)) from error
        if not math.isclose(resultado, ref["pm25_predicho"], rel_tol=0, abs_tol=1e-9):
            raise CommandError(f"Predicción divergente: {resultado}")
        self.stdout.write(f"Tunal · 17 columnas · {resultado} µg/m³")
