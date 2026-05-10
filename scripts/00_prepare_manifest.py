#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
00_prepare_manifest.py

Construit site/data/manifest.csv à partir des PDF déposés dans site/pdf/.

Version renforcée :
- lit le code officiel sur la première page du PDF quand c'est possible ;
- détecte l'année, le jour et la zone à partir de codes du type 23-PYCJ1ME3 ;
- utilise le nom du fichier comme repli si l'extraction de la première page échoue ;
- conserve les colonnes attendues par les scripts suivants.

À lancer depuis la racine du projet :
    python3 scripts/00_prepare_manifest.py

Options utiles :
    python3 scripts/00_prepare_manifest.py --force
    python3 scripts/00_prepare_manifest.py --no-backup
    python3 scripts/00_prepare_manifest.py --root /chemin/vers/revisions
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


# Correspondances fournies par l'utilisateur.
ZONE_LABELS = {
    "ME": "Métropole, Mayotte, La Réunion, Antilles Guyane",
    "AN": "Amérique du Nord",
    "JA": "Asie",
    "G1": "Centres étrangers",
    "PO": "Polynésie",
    "AS": "Amérique du Sud",
    "NC": "Nouvelle-Calédonie",
    "LR": "La Réunion",
    "LI": "Centres étrangers",
    "BI": "Centres étrangers",
    "PE": "Centres étrangers",
}

# Codes triés du plus long au plus court pour éviter les ambiguïtés.
ZONE_CODES = sorted(ZONE_LABELS.keys(), key=len, reverse=True)

CSV_COLUMNS = [
    "enabled",
    "id",
    "titre",
    "annee",
    "session",
    "zone",
    "pdf_path",
    "sha256",
    "notes",
]


@dataclass
class SubjectMeta:
    code: str = ""
    year: str = ""
    day: str = ""
    zone_code: str = ""
    zone_label: str = "À préciser"
    confidence: str = "faible"
    source: str = ""
    notes: str = ""

    @property
    def session(self) -> str:
        if self.day in {"1", "2"}:
            return f"Jour {self.day}"
        if self.day:
            return f"Session {self.day}"
        return "À préciser"


def project_root_from_script() -> Path:
    """Racine attendue : parent du dossier scripts/."""
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(value: str, max_len: int = 90) -> str:
    value = value.lower()
    value = value.replace("œ", "oe").replace("æ", "ae")
    # Translitération légère pour les cas utiles ici.
    replacements = {
        "à": "a", "â": "a", "ä": "a",
        "ç": "c",
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "î": "i", "ï": "i",
        "ô": "o", "ö": "o",
        "ù": "u", "û": "u", "ü": "u",
        "ÿ": "y",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    value = re.sub(r"-+", "-", value)
    if len(value) > max_len:
        value = value[:max_len].strip("-")
    return value or "sujet"


def normalize_for_code_search(text: str) -> str:
    # Supprime les espaces parasites générés par certains extracteurs PDF.
    text = text.upper()
    text = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2012", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s+", "", text)
    return text


def extract_first_page_text_with_pdfplumber(pdf_path: Path) -> str:
    import pdfplumber  # type: ignore

    with pdfplumber.open(str(pdf_path)) as pdf:
        if not pdf.pages:
            return ""
        return pdf.pages[0].extract_text(x_tolerance=1, y_tolerance=3) or ""


def extract_first_page_text_with_pymupdf(pdf_path: Path) -> str:
    import fitz  # type: ignore

    doc = fitz.open(str(pdf_path))
    try:
        if doc.page_count == 0:
            return ""
        page = doc.load_page(0)
        return page.get_text("text") or ""
    finally:
        doc.close()


def extract_first_page_text(pdf_path: Path) -> str:
    """Extraction sans OCR. Repli PyMuPDF si pdfplumber échoue."""
    errors: list[str] = []
    try:
        text = extract_first_page_text_with_pdfplumber(pdf_path)
        if text.strip():
            return text
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pdfplumber: {exc}")

    try:
        text = extract_first_page_text_with_pymupdf(pdf_path)
        if text.strip():
            return text
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pymupdf: {exc}")

    return ""


def find_subject_code(raw_text_or_name: str) -> Optional[str]:
    """
    Recherche un code officiel du type :
      23-PYCJ1ME3, 22PYCJ2G11, 25-PYCJ1NC1

    Retourne une forme normalisée sans séparateurs : 23PYCJ1ME3.
    """
    s = normalize_for_code_search(raw_text_or_name)

    # Cas standard : YY-PYC-J[1/2]-ZONE[-VARIANTE]
    # La queue après J1/J2 peut être ME3, G11, AN1, etc.
    pattern = re.compile(r"(?P<yy>\d{2})[-_]?PYCJ(?P<day>[12])(?P<tail>[A-Z0-9]{2,6})")
    matches = list(pattern.finditer(s))

    # On privilégie les occurrences proches du début, car le code officiel est en tête de première page.
    if matches:
        return matches[0].group(0).replace("-", "").replace("_", "")

    # Cas marginal observé dans certains noms : YY-PYCPE2V1.
    # Il n'a pas la forme J1/J2, mais PE est une zone fournie dans la table.
    pattern_pe = re.compile(r"(?P<yy>\d{2})[-_]?PYC(?P<zone>PE)(?P<day>[0-9])(?P<tail>[A-Z0-9]{0,4})")
    match_pe = pattern_pe.search(s)
    if match_pe:
        return match_pe.group(0).replace("-", "").replace("_", "")

    return None


def decode_standard_code(code: str, source: str) -> SubjectMeta:
    """Décode les codes standard YYPYCJ{jour}{zone}{variante}."""
    code = normalize_for_code_search(code)
    meta = SubjectMeta(code=code, source=source)

    m = re.match(r"(?P<yy>\d{2})PYCJ(?P<day>[12])(?P<tail>[A-Z0-9]{2,6})", code)
    if m:
        yy = m.group("yy")
        tail = m.group("tail")
        meta.year = f"20{yy}"
        meta.day = m.group("day")
        for zc in ZONE_CODES:
            if tail.startswith(zc):
                meta.zone_code = zc
                meta.zone_label = ZONE_LABELS[zc]
                meta.confidence = "forte"
                meta.notes = f"Code détecté ({source}) : {code} ; zone={zc}."
                return meta
        meta.confidence = "moyenne"
        meta.notes = f"Code détecté ({source}) : {code}, mais zone inconnue dans la queue '{tail}'."
        return meta

    # Cas marginal : YYPYCPE2V1.
    m_pe = re.match(r"(?P<yy>\d{2})PYC(?P<zone>PE)(?P<day>[0-9])(?P<tail>[A-Z0-9]{0,4})", code)
    if m_pe:
        yy = m_pe.group("yy")
        meta.year = f"20{yy}"
        meta.day = m_pe.group("day")
        meta.zone_code = "PE"
        meta.zone_label = ZONE_LABELS["PE"]
        meta.confidence = "moyenne"
        meta.notes = f"Code non standard détecté ({source}) : {code} ; interprétation prudente zone=PE."
        return meta

    meta.notes = f"Code non décodable : {code}."
    return meta


def infer_meta(pdf_path: Path, read_pdf_text: bool = True) -> SubjectMeta:
    """Extrait prioritairement le code sur la première page, puis se rabat sur le nom du fichier."""
    if read_pdf_text:
        first_page = extract_first_page_text(pdf_path)
        code = find_subject_code(first_page)
        if code:
            return decode_standard_code(code, source="première page")

    code = find_subject_code(pdf_path.name)
    if code:
        return decode_standard_code(code, source="nom du fichier")

    # Repli minimal : année par les deux premiers chiffres du nom si disponibles.
    meta = SubjectMeta(source="repli nom de fichier")
    m_year = re.search(r"(?<!\d)(2[1-9])", pdf_path.stem)
    if m_year:
        meta.year = f"20{m_year.group(1)}"
    m_day = re.search(r"j\s*([12])", pdf_path.stem, flags=re.IGNORECASE)
    if m_day:
        meta.day = m_day.group(1)
    meta.notes = "À relire : code officiel non détecté ; compléter annee/session/zone/titre si nécessaire."
    return meta


def build_row(pdf_path: Path, site_dir: Path, read_pdf_text: bool = True) -> dict[str, str]:
    meta = infer_meta(pdf_path, read_pdf_text=read_pdf_text)
    rel_pdf = pdf_path.relative_to(site_dir).as_posix()
    stem = pdf_path.stem

    year_for_id = meta.year or "annee"
    session_for_id = slugify(meta.session)
    zone_for_id = slugify(meta.zone_code or meta.zone_label)
    stem_for_id = slugify(stem, max_len=55)
    subject_id = slugify(f"{year_for_id}-{session_for_id}-{zone_for_id}-{stem_for_id}", max_len=120)

    notes = meta.notes
    if meta.confidence != "forte":
        notes = (notes + " " if notes else "") + "À relire manuellement."

    return {
        "enabled": "1",
        "id": subject_id,
        "titre": stem,
        "annee": meta.year,
        "session": meta.session,
        "zone": meta.zone_label,
        "pdf_path": rel_pdf,
        "sha256": sha256_file(pdf_path),
        "notes": notes.strip(),
    }


def write_manifest(rows: list[dict[str, str]], output_path: Path, backup: bool = True, force: bool = False) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and backup:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = output_path.with_suffix(output_path.suffix + f".{timestamp}.bak")
        shutil.copy2(output_path, backup_path)
        print(f"Backup créé : {backup_path}")

    if output_path.exists() and not force:
        # On écrase quand même, mais on le signale clairement : le comportement historique du script était de régénérer.
        print(f"INFO manifest existant remplacé : {output_path}")

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, str]], output_path: Path) -> None:
    zones = Counter(r["zone"] or "À préciser" for r in rows)
    years = Counter(r["annee"] or "À préciser" for r in rows)
    sessions = Counter(r["session"] or "À préciser" for r in rows)
    unresolved = [r for r in rows if (not r["annee"] or r["zone"] == "À préciser" or "À relire" in r["notes"])]

    print(f"Manifest généré : {output_path}")
    print(f"Sujets détectés : {len(rows)}")
    print("\nRépartition par année :")
    for key, count in sorted(years.items()):
        print(f"  {key}: {count}")
    print("\nRépartition par session :")
    for key, count in sorted(sessions.items()):
        print(f"  {key}: {count}")
    print("\nRépartition par zone :")
    for key, count in sorted(zones.items()):
        print(f"  {key}: {count}")

    if unresolved:
        print(f"\nLignes à relire : {len(unresolved)}")
        for r in unresolved[:15]:
            print(f"  - {r['pdf_path']} | annee={r['annee'] or '??'} | session={r['session']} | zone={r['zone']}")
        if len(unresolved) > 15:
            print(f"  ... +{len(unresolved) - 15} autres")
    else:
        print("\nAucune ligne manifestement incomplète.")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère site/data/manifest.csv à partir de site/pdf/*.pdf")
    parser.add_argument("--root", type=Path, default=project_root_from_script(), help="Racine du projet. Par défaut : parent de scripts/.")
    parser.add_argument("--pdf-dir", type=Path, default=None, help="Dossier des PDF. Par défaut : <root>/site/pdf")
    parser.add_argument("--output", type=Path, default=None, help="Manifest de sortie. Par défaut : <root>/site/data/manifest.csv")
    parser.add_argument("--force", action="store_true", help="Régénère le manifest même s'il existe déjà.")
    parser.add_argument("--no-backup", action="store_true", help="Ne crée pas de sauvegarde de l'ancien manifest.csv.")
    parser.add_argument("--no-pdf-text", action="store_true", help="Ne lit pas la première page des PDF ; utilise seulement les noms de fichiers.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    site_dir = root / "site"
    pdf_dir = args.pdf_dir.resolve() if args.pdf_dir else site_dir / "pdf"
    output_path = args.output.resolve() if args.output else site_dir / "data" / "manifest.csv"

    if not pdf_dir.exists():
        print(f"ERREUR dossier PDF introuvable : {pdf_dir}", file=sys.stderr)
        return 2

    pdfs = sorted(pdf_dir.glob("*.pdf"), key=lambda p: p.name.lower())
    if not pdfs:
        print(f"ERREUR aucun PDF trouvé dans : {pdf_dir}", file=sys.stderr)
        return 2

    rows: list[dict[str, str]] = []
    read_pdf_text = not args.no_pdf_text
    for i, pdf_path in enumerate(pdfs, start=1):
        print(f"[{i:03d}/{len(pdfs):03d}] analyse : {pdf_path.name}")
        try:
            rows.append(build_row(pdf_path, site_dir=site_dir, read_pdf_text=read_pdf_text))
        except Exception as exc:  # noqa: BLE001
            print(f"  ERREUR sur {pdf_path.name}: {exc}", file=sys.stderr)
            rel_pdf = pdf_path.relative_to(site_dir).as_posix() if site_dir in pdf_path.parents else pdf_path.as_posix()
            rows.append({
                "enabled": "0",
                "id": slugify(pdf_path.stem),
                "titre": pdf_path.stem,
                "annee": "",
                "session": "À préciser",
                "zone": "À préciser",
                "pdf_path": rel_pdf,
                "sha256": sha256_file(pdf_path) if pdf_path.exists() else "",
                "notes": f"ERREUR pendant l'analyse : {exc}",
            })

    write_manifest(rows, output_path=output_path, backup=not args.no_backup, force=args.force)
    print_summary(rows, output_path=output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
