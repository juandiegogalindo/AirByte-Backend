from pathlib import Path

import joblib
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand
from sklearn.ensemble import HistGradientBoostingRegressor

from aire.inferencia import ESTACIONES, RETARDOS, TIPOS, VARIABLES


class Command(BaseCommand):
    help = "Entrena y evalúa un modelo por horizonte horario usando observaciones de RMCAB."

    def add_arguments(self, parser):
        parser.add_argument("--archivo", required=True, type=Path)

    def handle(self, *args, archivo, **options):
        datos = pd.read_csv(archivo, parse_dates=["fecha_hora"])
        datos = datos.drop_duplicates(["estacion", "fecha_hora"], keep="last")
        for variable in VARIABLES:
            numero = pd.to_numeric(datos[variable], errors="coerce")
            datos[variable] = numero.where(numero.lt(1000))
        horas = datos["fecha_hora"]
        pm25 = datos.set_index(["estacion", "fecha_hora"])["PM2.5"]

        def observado(desfase):
            indice = pd.MultiIndex.from_arrays([datos["estacion"], horas + pd.Timedelta(hours=desfase)])
            return pm25.reindex(indice).to_numpy()

        x = datos[list(VARIABLES)].rename(columns=lambda nombre: f"{nombre}_actual")
        x = x.assign(hora=horas.dt.hour, mes=horas.dt.month)
        for estacion in ESTACIONES:
            x[f"estacion_{estacion}"] = datos["estacion"].eq(estacion)
        for h in RETARDOS:
            x[f"pm25_hace_{h}h"] = observado(-h)
        x = x[list(TIPOS)].astype(TIPOS)
        modelos, metricas = {}, {}
        for h in range(1, 25):
            objetivo = observado(h)
            destino = horas + pd.Timedelta(hours=h)
            disponible = pd.notna(objetivo) & datos["PM2.5"].notna()
            entrenar = disponible & destino.lt("2024-01-01")
            evaluar = disponible & horas.ge("2025-01-01") & destino.lt("2026-01-01")
            modelo = HistGradientBoostingRegressor(max_iter=70, max_leaf_nodes=23, random_state=42)
            modelo.fit(x.loc[entrenar], objetivo[entrenar])
            real = objetivo[evaluar]
            metricas[h] = {"n": len(real), "mae": float(abs(modelo.predict(x.loc[evaluar]) - real).mean()),
                "persistencia": float(abs(x.loc[evaluar, "PM2.5_actual"] - real).mean())}
            modelos[h] = modelo
            self.stdout.write(f"+{h:02d} h: {metricas[h]}")
        salida = settings.ROOT / "modelo/air_byte_pm25_horario.joblib"
        temporal = salida.with_suffix(".tmp")
        joblib.dump({"modelos": modelos, "metricas_2025": metricas}, temporal, compress=3)
        temporal.replace(salida)

