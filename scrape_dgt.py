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
  
SENTIDO_TARGETS = [
    "AMBOS SENTIDOS",
    "CRECIENTE DE LA KILOMETRACIÓN",
    "DECRECIENTE DE LA KILOMETRACIÓN",
]
NIVELES = ["NEGRO", "ROJO", "AMARILLO", "VERDE", "NO APLICA"]
 

def fold(s):
    """Strip whitespace, accents, and case so text can be compared even if
    a PDF line-wrap inserted/removed a space or mangled an accented char."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", "", s).upper()
 
 
SENTIDO_FOLDED = {fold(t): t for t in SENTIDO_TARGETS}
MAX_SENTIDO_WORDS = max(len(t.split()) for t in SENTIDO_TARGETS) + 2  # slack for stray splits
 
# A road code is only trusted when directly followed by two mileage numbers —
# this avoids false positives from road-like text that sometimes appears
# inside the free-form "HACIA" field (e.g. "El Alcor M-600 ZARZALEJO").
ROAD_PK_RE = re.compile(
    r"([A-Z]{1,4}-\d+[A-Z]?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+"
)
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
    mileage numbers; any line lacking that pattern is a leftover fragment.
 
    Such a fragment usually continues the row just built — but if that row
    already has its NIVEL token (i.e. it looks "closed"), the fragment more
    likely belongs to the row that's about to start next (pdfplumber can
    emit a wrapped fragment slightly out of order). In that case it's held
    and prepended to the next row-start line instead.
    """
    merged = []
    pending_prefix = ""
    for line in lines:
        road_m = ROAD_PK_RE.search(line)
        if road_m:
            if pending_prefix:
                line = line[: road_m.end()] + pending_prefix + " " + line[road_m.end():]
            merged.append(line)
            pending_prefix = ""
        elif merged and not NIVEL_RE.search(merged[-1]):
            merged[-1] = merged[-1].rstrip() + " " + line.lstrip()
        else:
            pending_prefix = (pending_prefix + " " + line).strip()
    return merged
 
 
def match_sentido(rest):
    """
    Find the SENTIDO value at the start of `rest` by trying increasing
    word-count windows and comparing their folded form against the known
    phrases. Folding strips all whitespace, so it doesn't matter whether a
    PDF wrap added a stray space mid-word or split cleanly between words —
    both fold to the same string as the correctly-formed original.
    """
    words = rest.split()
    for n in range(1, min(MAX_SENTIDO_WORDS, len(words)) + 1):
        candidate = " ".join(words[:n])
        folded = fold(candidate)
        if folded in SENTIDO_FOLDED:
            return SENTIDO_FOLDED[folded], " ".join(words[n:])
    return None, rest
 
 
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
 
    sentido, localizacion = match_sentido(rest)
    localizacion = localizacion.strip(" -")
    if sentido is None:
        sentido = "DESCONOCIDO"  # keep the row (a road closure), flag the field instead of guessing
 
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
 
