import csv
from collections import defaultdict
from statistics import median
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "datos" / "RMCAB" / "dataset_RMCAB_limpio.csv"
OUTPUT = ROOT / "datos" / "RMCAB" / "dataset_modelo_pm25_24h.csv"

NUMERIC = ["PM2.5", "PM10", "Precipitacion", "Temperatura", "Vel Viento", "Dir Viento"]
LAGS = [1, 3, 6, 12, 24]


def number(value):
    if value is None or value.strip().upper() in {"", "NA", "N/A", "NULL"}:
        return None
    try:
        x = float(value.replace(",", "."))
        # 8756 y valores similares son conteos de las filas de resumen.
        if x >= 1000:
            return None
        return x
    except ValueError:
        return None


def main():
    by_station = defaultdict(dict)
    with INPUT.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                dt = datetime.strptime(row["fecha_hora"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            values = {key: number(row.get(key, "")) for key in NUMERIC}
            by_station[row["estacion"]][dt] = values

    original_missing = {
        station: {dt: {v: measurements[dt][v] is None for v in NUMERIC}
                  for dt in measurements}
        for station, measurements in by_station.items()
    }

    # Imputación temporal únicamente para huecos cortos (hasta 3 horas).
    for station, measurements in by_station.items():
        dates = sorted(measurements)
        for variable in NUMERIC:
            for i, dt in enumerate(dates):
                if measurements[dt][variable] is not None:
                    continue
                before = next((dates[j] for j in range(i - 1, max(-1, i - 4), -1)
                               if measurements[dates[j]][variable] is not None), None)
                after = next((dates[j] for j in range(i + 1, min(len(dates), i + 4))
                              if measurements[dates[j]][variable] is not None), None)
                if before is not None and after is not None:
                    gap = (after - before).total_seconds() / 3600
                    if gap <= 4:
                        left = measurements[before][variable]
                        right = measurements[after][variable]
                        portion = (dt - before).total_seconds() / (after - before).total_seconds()
                        measurements[dt][variable] = left + portion * (right - left)

        # Para bloques largos, usar la mediana de la misma estación y hora.
        for variable in NUMERIC:
            by_hour = defaultdict(list)
            for dt in dates:
                value = measurements[dt][variable]
                if value is not None:
                    by_hour[dt.hour].append(value)
            overall = [value for dt in dates for value in [measurements[dt][variable]] if value is not None]
            fallback = median(overall) if overall else 0
            for dt in dates:
                if measurements[dt][variable] is None:
                    measurements[dt][variable] = median(by_hour[dt.hour]) if by_hour[dt.hour] else fallback

    fields = ["estacion", "fecha_hora"]
    fields += [f"{v}_actual" for v in NUMERIC]
    fields += [f"{v}_imputado" for v in NUMERIC]
    fields += [f"PM2.5_lag_{h}h" for h in LAGS]
    fields += ["PM2.5_objetivo_24h"]

    kept = 0
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for station in sorted(by_station):
            measurements = by_station[station]
            for dt in sorted(measurements):
                target_dt = dt + timedelta(hours=24)
                if target_dt not in measurements:
                    continue
                current = measurements[dt]
                target = measurements[target_dt]["PM2.5"]
                if original_missing[station][target_dt]["PM2.5"]:
                    continue
                out = {"estacion": station, "fecha_hora": dt.isoformat(sep=" ")}
                for variable in NUMERIC:
                    value = current[variable]
                    out[f"{variable}_actual"] = "" if value is None else value
                    out[f"{variable}_imputado"] = int(original_missing[station][dt][variable])
                for lag in LAGS:
                    value = measurements.get(dt - timedelta(hours=lag), {}).get("PM2.5")
                    out[f"PM2.5_lag_{lag}h"] = "" if value is None else value
                out["PM2.5_objetivo_24h"] = target
                writer.writerow(out)
                kept += 1

    print(f"Estaciones: {len(by_station)}")
    print(f"Registros para modelado: {kept}")
    print(f"Salida: {OUTPUT}")


if __name__ == "__main__":
    main()
