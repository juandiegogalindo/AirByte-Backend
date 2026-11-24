from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .actual import BOGOTA, VERSION
from .models import Estacion, MedicionHoraria, VersionHistorico


class ActualTest(TestCase):
    def test_24_horizontes_y_lectura_atrasada(self):
        version = VersionHistorico.objects.create(codigo=VERSION, sha256="", fuente="RMCAB")
        estacion = Estacion.objects.get(slug="tunal")
        emision = timezone.now().replace(minute=0, second=0, microsecond=0)
        MedicionHoraria.objects.create(version=version, estacion=estacion, instante=emision,
                                      pm25=23, archivo_origen="RMCAB")
        with patch("aire.views.actualizar_si_corresponde"), patch("aire.views.pronosticar_24",
                return_value=[(h, float(h)) for h in range(1, 25)]):
            datos = self.client.get("/api/v1/actual", {"estacion": "tunal"}).json()
            self.assertEqual(datos["medicion"]["pm25"], 23)
            self.assertEqual([h["pm25"] for h in datos["horas"]], list(range(1, 25)))
            self.assertEqual(datos["horas"][-1]["hora"], (emision + timedelta(hours=24)).astimezone(BOGOTA).isoformat())
            MedicionHoraria.objects.update(instante=emision - timedelta(hours=4))
            atrasada = self.client.get("/api/v1/actual", {"estacion": "tunal"}).json()
            self.assertEqual(atrasada["estado"], "lectura_atrasada")
            self.assertFalse(atrasada["horas"])
