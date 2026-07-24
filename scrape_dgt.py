#!/usr/bin/env python3
"""
Downloads the DGT "Carreteras Cortadas por Incendios" PDF and converts it
into a structured JSON file (data/carreteras.json) that a static webpage
can read. Designed to be run hourly by a GitHub Actions cron job.
"""

import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
 
PDF_URL = "https://www.dgt.es/estaticos/movilidad/CarreterasCortadasIncendios.pdf"
OUT_PATH = "data/carreteras.json"
 
SENTIDO_PATTERNS = [
    r"AMBOS SENTIDOS",
    r"CRECIENTE DE LA KILOMETRACI.N",     # '.' tolerates any encoding of the accented O
    r"DECRECIENTE DE LA KILOMETRACI.N",
]
NIVELES = ["NEGRO", "ROJO", "AMARILLO", "VERDE", "NO APLICA"]
 
# A road code is only trusted when directly followed by two mileage numbers —
# this avoids false positives from road-like text that sometimes appears
# inside the free-form "HACIA" field (e.g. "El Alcor M-600 ZARZALEJO").
ROAD_PK_RE = re.compile(
    r"([A-Z]{1,4}-\d+[A-Z]?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+"
)
SENTIDO_RE = re.compile("(" + "|".join(SENTIDO_PATTERNS) + ")")
NIVEL_RE = re.compile(r"\b(" + "|".join(re.escape(n) for n in NIVELES) + r")\b")
 
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
            page_lines = []
            for line in text.split("\n"):
                line = unicodedata.normalize("NFC", line.strip())
                if not line:
                    continue
                if any(p in line for p in SKIP_PATTERNS):
                    continue
                page_lines.append(line)
            lines.extend(merge_wrapped_lines(page_lines))
    return lines
 
 
def merge_wrapped_lines(lines):
    """
    pdfplumber's extract_text() can wrap a long cell value (e.g. 'CRECIENTE
    DE LA KILOMETRACIÓN') onto its own line when the column is narrow. A
    genuine new row always contains a road code directly followed by two
    mileage numbers; any line lacking that pattern is a leftover fragment
    of the previous row and gets merged back onto it.
    """
    merged = []
    for line in lines:
        if ROAD_PK_RE.search(line) or not merged:
            merged.append(line)
        else:
            merged[-1] = merged[-1].rstrip() + " " + line.lstrip()
    return merged
 
 
def parse_line(line):
    """
    Rows look like:
    <ZONA (comunidad+provincia)> <CARRETERA> <PK_INI> <PK_FIN> <SENTIDO> <LOCALIZACIÓN [+HACIA]> <NIVEL>
    Zona/localización text is free-form, so we anchor on the tokens we CAN
    identify reliably: NIVEL at the very end, and a road code immediately
    followed by two mileage numbers (which only ever occurs once per row,
    right after the zona).
    """
    nivel_m = list(NIVEL_RE.finditer(line))
    if not nivel_m:
        return None
    nivel = nivel_m[-1].group(1)
    line_wo_nivel = line[: nivel_m[-1].start()].rstrip()
 
    road_m = ROAD_PK_RE.search(line_wo_nivel)
    if not road_m:
        return None
    carretera = road_m.group(1)
    pk_ini, pk_fin = road_m.group(2), road_m.group(3)
    zona = line_wo_nivel[: road_m.start(1)].strip()
    rest = line_wo_nivel[road_m.end():].strip()
 
    sentido_m = SENTIDO_RE.match(rest)
    if sentido_m:
        sentido = sentido_m.group(0)
        localizacion = rest[sentido_m.end():].strip(" -")
    else:
        # Unknown/garbled SENTIDO phrasing: fall back to taking the leading
        # run of all-caps words as sentido (LOCALIZACIÓN is mixed-case, so
        # the first word containing a lowercase letter marks the boundary).
        words = rest.split(" ")
        upper_words, i = [], 0
        for w in words:
            if w and not any(ch.islower() for ch in w):
                upper_words.append(w)
                i += 1
            else:
                break
        sentido = " ".join(upper_words) if upper_words else None
        localizacion = " ".join(words[i:]).strip(" -")
 
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
 
