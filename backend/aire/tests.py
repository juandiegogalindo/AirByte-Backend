import io
import json
from datetime import datetime
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from .inferencia import predecir
from .models import MedicionHoraria
from .views import entradas


def referencia():
    return json.loads((settings.ROOT / "notebooks/prediccion_referencia.json").read_text(encoding="utf-8"))


class ModeloTest(SimpleTestCase):
    def test_artefacto(self):
        datos = referencia()
        self.assertAlmostEqual(predecir(datos["entradas"]), datos["pm25_predicho"], delta=1e-9)


@override_settings(HISTORICO="muestra-tunal")
class HistoricoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ruta = settings.BASE_DIR / "aire/fixtures/tunal.csv"
        call_command("importar_rmcab", archivo=cls.ruta, version_datos="muestra-tunal", stdout=io.StringIO())

    def consultar(self, **cambios):
        return self.client.get("/api/v1/consulta", {"estacion": "tunal",
            "emision": "2025-01-01T06:00:00Z", "evaluar": "true", **cambios})

    def test_consulta_real_y_futuro_independiente(self):
        ref = referencia()
        inicio = datetime.fromisoformat("2025-01-01T01:00:00-05:00")
        self.assertEqual(connection.vendor, "postgresql")
        with patch("aire.views.entradas", wraps=entradas) as vector:
            respuesta = self.consultar()
            self.assertEqual(respuesta.status_code, 200)
            args = vector.call_args.args
            self.assertEqual(entradas(*args), ref["entradas"])
        datos = respuesta.json()
        self.assertEqual(datos["medicion"]["pm25"], 42)
        self.assertEqual(datos["emision"], inicio.isoformat())
        self.assertEqual(datos["pronostico"]["hora"], "2025-01-02T01:00:00-05:00")
        self.assertAlmostEqual(datos["pronostico"]["pm25"], ref["pm25_predicho"], delta=1e-9)
        self.assertEqual(datos["evaluacion"]["pm25_observado"], 12)
        futuro = MedicionHoraria.objects.filter(instante__gt=inicio)
        futuro.update(pm25=999)
        posterior = self.consultar().json()
        self.assertEqual(posterior["pronostico"], datos["pronostico"])
        self.assertEqual(posterior["evaluacion"]["pm25_observado"], 999)
        futuro.delete()
        self.assertEqual(self.consultar().json()["pronostico"], datos["pronostico"])

    def test_importar_dos_veces(self):
        antes = list(MedicionHoraria.objects.order_by("id").values())
        call_command("importar_rmcab", archivo=self.ruta, version_datos="muestra-tunal", stdout=io.StringIO())
        self.assertEqual(list(MedicionHoraria.objects.order_by("id").values()), antes)

    def test_fallos_y_huecos(self):
        self.assertEqual(self.consultar(estacion="desconocida").status_code, 404)
        self.assertEqual(self.consultar(emision="2025-01-01T06:00:00").status_code, 400)
        self.assertEqual(self.consultar(emision="2026-01-01T06:00:00Z").status_code, 422)
        hueco = self.consultar(emision="2025-01-01T05:00:00Z").json()
        self.assertEqual(hueco["estado"], "sin_medicion_en_emision")
        self.assertEqual(hueco["medicion"]["antiguedad_minutos"], 120)
        self.assertIsNone(hueco["pronostico"])
        with self.settings(MODEL_PATH=self.ruta.with_name("ausente.joblib")):
            self.assertEqual(self.consultar().status_code, 503)

    def test_medianoche(self):
        from .management.commands.importar_rmcab import instante_local
        self.assertEqual(instante_local("31-12-2024 24:00").isoformat(), "2025-01-01T00:00:00-05:00")

