import argparse
import csv
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path("datos/RMCAB")
OUT = ROOT / "dataset_RMCAB_limpio.csv"
QUALITY = ROOT / "calidad_dataset_RMCAB.csv"
CATALOG = ROOT / "catalogo_variables_RMCAB.csv"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MISSING = {"", "----", "-", "NA", "N/A", "null", "None"}


def shared_strings(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    text_tag = "{" + NS["m"] + "}t"
    return ["".join(t.text or "" for t in si.iter(text_tag)) for si in root.findall("m:si", NS)]


def cell_value(cell, strings):
    if cell.get("t") == "inlineStr":
        text_tag = "{" + NS["m"] + "}t"
        return "".join(t.text or "" for t in cell.iter(text_tag))
    node = cell.find("m:v", NS)
    if node is None:
        return ""
    value = node.text or ""
    if cell.get("t") == "s":
        return strings[int(value)]
    return value


def read_workbook(path, *, recuperar_medianoche=False):
    with zipfile.ZipFile(path) as z:
        strings = shared_strings(z)
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows = []
        for row in sheet.findall(".//m:sheetData/m:row", NS):
            vals = {}
            for cell in row.findall("m:c", NS):
                ref = cell.get("r", "")
                col = re.match(r"([A-Z]+)", ref).group(1)
                vals[col] = cell_value(cell, strings).strip()
            rows.append((int(row.get("r", "0")), vals))
    by_number = dict(rows)
    if by_number.get(3, {}).get("A") != "DateTime":
        return [], {}, {}
    cols = sorted(by_number[3], key=lambda c: (len(c), c))
    variables = {c: by_number.get(4, {}).get(c, "").strip() for c in cols if c != "A" and by_number.get(4, {}).get(c, "").strip()}
    units = {c: by_number.get(5, {}).get(c, "").strip() for c in variables}
    data = []
    for row_number, row in rows:
        if row_number < 6:
            continue
        dt = row.get("A", "").strip()
        if not dt:
            continue
        try:
            if recuperar_medianoche and dt.endswith(" 24:00"):
                dt = (datetime.strptime(dt[:10], "%d-%m-%Y") + timedelta(days=1)).isoformat(sep=" ")
            else:
                dt = datetime.strptime(dt, "%d-%m-%Y %H:%M").isoformat(sep=" ")
        except ValueError:
            pass
        data.append((dt, {variables[c]: row.get(c, "").strip() for c in variables}))
    return data, variables, units


def clean_value(value):
    if value in MISSING:
        return "NA"
    try:
        number = float(value.replace(",", "."))
        return str(int(number)) if number.is_integer() else str(number)
    except ValueError:
        return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recuperar-medianoche", action="store_true")
    opciones = parser.parse_args()
    sufijo = "_v2" if opciones.recuperar_medianoche else ""
    salida = OUT.with_stem(OUT.stem + sufijo)
    files = sorted(ROOT.rglob("*.xlsx"))
    records = []
    all_vars = set()
    units = {}
    quality = Counter()
    variable_missing = Counter()
    variable_total = Counter()
    for path in files:
        data, variables, file_units = read_workbook(path, recuperar_medianoche=opciones.recuperar_medianoche)
        station = path.parent.parent.parent.name
        if station == "RMCAB":
            station = path.parent.parent.name
        source = str(path.relative_to(ROOT)).replace("\\", "/")
        all_vars.update(variables.values())
        units.update({k: v for k, v in file_units.items() if v})
        quality["archivos_procesados"] += 1
        quality["filas_procesadas"] += len(data)
        for dt, measurements in data:
            # Los libros de la RMCAB incluyen filas de estadísticos al final
            # (Summary, Minimum, Average, etc.). Solo consolidamos mediciones
            # horarias con fecha válida.
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", dt):
                continue
            row = {"estacion": station, "fecha_hora": dt, "archivo_origen": source}
            for variable, value in measurements.items():
                variable_total[variable] += 1
                if value in MISSING:
                    variable_missing[variable] += 1
                row[variable] = clean_value(value)
            records.append(row)
    headers = ["estacion", "fecha_hora", "archivo_origen"] + sorted(all_vars)
    with salida.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    with QUALITY.with_stem(QUALITY.stem + sufijo).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["indicador", "valor"])
        writer.writerow(["archivos_encontrados", len(files)])
        writer.writerow(["archivos_procesados", quality["archivos_procesados"]])
        writer.writerow(["filas_procesadas", quality["filas_procesadas"]])
        writer.writerow(["variables_unicas", len(all_vars)])
        writer.writerow(["registros_con_NA", sum(variable_missing.values())])
        writer.writerow([])
        writer.writerow(["variable", "mediciones", "faltantes_NA", "porcentaje_faltante"])
        for variable in sorted(all_vars):
            total = variable_total[variable]
            missing = variable_missing[variable]
            writer.writerow([variable, total, missing, round(100 * missing / total, 2) if total else 0])
    with CATALOG.with_stem(CATALOG.stem + sufijo).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["variable", "unidad"])
        for variable in sorted(all_vars):
            writer.writerow([variable, units.get(variable, "")])
    print(f"Archivos procesados: {len(files)}")
    print(f"Filas consolidadas: {len(records)}")
    print(f"Variables: {len(all_vars)}")
    print(f"Salida: {salida}")


if __name__ == "__main__":
    main()
