#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

from config import DEFAULT_DPI, IMG_DIR, MANIFEST_CSV, PAGES_DIR, SITE_ROOT
from utils import clean_pdf_text, ensure_dirs, read_csv_dicts, site_relative, write_json


def enabled(row: dict[str, str]) -> bool:
    return str(row.get("enabled", "1")).strip().lower() not in {"0", "false", "non", "no"}


def extract_one(row: dict[str, str], dpi: int = DEFAULT_DPI, force: bool = False) -> dict:
    source_id = row["id"]
    pdf_path = SITE_ROOT / row["pdf_path"]
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF introuvable pour {source_id}: {pdf_path}")

    out_json = PAGES_DIR / f"{source_id}.json"
    out_img_dir = IMG_DIR / source_id
    ensure_dirs(PAGES_DIR, out_img_dir)

    if out_json.exists() and not force:
        return {"id": source_id, "status": "skipped", "reason": "already extracted"}

    text_by_page: dict[int, str] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            except Exception as exc:  # noqa: BLE001
                text = f"[ERREUR EXTRACTION TEXTE PAGE {i}: {exc}]"
            text_by_page[i] = clean_pdf_text(text)

    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pages = []
    for index, page in enumerate(doc, start=1):
        img_name = f"page_{index:02d}.png"
        img_path = out_img_dir / img_name
        if force or not img_path.exists():
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pix.save(str(img_path))
        pages.append(
            {
                "page": index,
                "text": text_by_page.get(index, ""),
                "image": site_relative(img_path, SITE_ROOT),
            }
        )
    doc.close()

    result = {
        "source_id": source_id,
        "titre": row.get("titre", ""),
        "annee": row.get("annee", ""),
        "session": row.get("session", ""),
        "zone": row.get("zone", ""),
        "pdf_path": row.get("pdf_path", ""),
        "page_count": len(pages),
        "dpi": dpi,
        "pages": pages,
    }
    write_json(out_json, result)
    return {"id": source_id, "status": "ok", "pages": len(pages)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrait le texte des PDF et rend chaque page en PNG.")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_CSV)
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Nombre maximum de sujets à traiter, utile pour un lot pilote.")
    args = parser.parse_args()

    rows = [r for r in read_csv_dicts(args.manifest) if enabled(r)]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("Aucun sujet activé dans le manifest.", file=sys.stderr)
        sys.exit(1)

    ok = 0
    for row in rows:
        try:
            res = extract_one(row, dpi=args.dpi, force=args.force)
            print(res)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print({"id": row.get("id"), "status": "error", "error": str(exc)}, file=sys.stderr)
    print(f"Extraction terminée : {ok}/{len(rows)} sujets traités.")


if __name__ == "__main__":
    main()
