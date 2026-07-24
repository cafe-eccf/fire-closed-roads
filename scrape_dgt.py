#!/usr/bin/env python3
"""
Downloads the DGT "Carreteras Cortadas por Incendios" PDF and converts it
into a structured JSON file (data/carreteras.json) that a static webpage
can read. Designed to be run hourly by a GitHub Actions cron job.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

PDF_URL = "https://www.dgt.es/estaticos/movilidad/CarreterasCortadasIncendios.pdf"
OUT_PATH = "data/carreteras.json"

SENTIDOS = [
    "AMBOS SENTIDOS",
    "CRECIENTE DE LA KILOMETRACIÓN",
    "DECRECIENTE DE LA KILOMETRACIÓN",
]
NIVELES = ["NEGRO", "ROJO", "AMARILLO", "VERDE"]

ROAD_RE = re.compile(r"\b([A-Z]{1,4}-\d+[A-Z]?)\b")
PK_RE = re.compile(r"\d+(?:\.\d+)?")
SENTIDO_RE = re.compile("|".join(re.escape(s) for s in SENTIDOS))
NIVEL_RE = re.compile(r"\b(" + "|".join(NIVELES) + r")\b")

# lines to ignore (headers/footers repeated on every PDF page)
SKIP_PATTERNS = [
    "CUADRO DE MANDOS",
    "COMUNIDAD PROVINCIA CARRETERA",
    "Puede obtener información adicional",
    "Fecha de generación del PDF",
]


def download_pdf(path="carreteras.pdf"):
    req = urllib.request.Request(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(path, "wb") as f:
        f.write(resp.read())
    return path


def pdf_to_lines(pdf_path):
    """Extract text preserving row order using pdfplumber."""
    import pdfplumber

    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=False) or ""
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if any(p in line for p in SKIP_PATTERNS):
                    continue
                lines.append(line)
    return lines


def parse_line(line):
    """
    Rows look like:
    <ZONA (comunidad+provincia)> <CARRETERA> <PK_INI> <PK_FIN> <SENTIDO> <LOCALIZACIÓN [+HACIA]> <NIVEL>
    Zona/localización text is free-form, so we anchor on the tokens we CAN
    identify reliably: the road code, the PK numbers, the sentido enum,
    and the nivel enum at the end.
    """
    nivel_m = list(NIVEL_RE.finditer(line))
    if not nivel_m:
        return None
    nivel = nivel_m[-1].group(1)
    body = line[: nivel_m[-1].start()].strip()

    sentido_m = SENTIDO_RE.search(body)
    if not sentido_m:
        return None
    sentido = sentido_m.group(0)
    before_sentido = body[: sentido_m.start()].strip()
    localizacion = body[sentido_m.end():].strip(" -")

    road_matches = list(ROAD_RE.finditer(before_sentido))
    if not road_matches:
        return None
    road_m = road_matches[-1]
    carretera = road_m.group(1)
    zona = before_sentido[: road_m.start()].strip()
    after_road = before_sentido[road_m.end():].strip()

    pk_nums = PK_RE.findall(after_road)
    pk_ini = pk_nums[0] if len(pk_nums) > 0 else None
    pk_fin = pk_nums[1] if len(pk_nums) > 1 else None

    return {
        "zona": zona,
        "carretera": carretera,
        "pk_ini": pk_ini,
        "pk_fin": pk_fin,
        "sentido": sentido,
        "localizacion": localizacion,
        "nivel": nivel,
    }


def main():
    pdf_path = download_pdf()
    lines = pdf_to_lines(pdf_path)

    records = []
    unparsed = []
    for line in lines:
        rec = parse_line(line)
        if rec:
            records.append(rec)
        else:
            unparsed.append(line)

    out = {
        "source_url": PDF_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "roads": records,
        "unparsed_lines": unparsed,  # kept for debugging/transparency, empty ideally
    }

    import os
    os.makedirs("data", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(records)} road closures to {OUT_PATH} "
          f"({len(unparsed)} unparsed lines)")
    if unparsed:
        print("Unparsed sample:", unparsed[:3], file=sys.stderr)


if __name__ == "__main__":
    main()
