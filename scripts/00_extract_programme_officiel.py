#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from config import (
    ALLOWED_THEMES,
    DATA_DIR,
    PROGRAMME_JSON,
    PROGRAMME_OFFICIEL_RAW_JSON,
    PROGRAMME_PDF_PATH,
    SITE_ROOT,
)
from utils import clean_pdf_text, ensure_dirs, now_timestamp, read_json, slugify, write_json

SECTION_SPECS = [
    {
        "id": "mesure-incertitudes",
        "titre": "Mesure et incertitudes",
        "type": "transversal",
        "marker": " Mesure et incertitudes",
        "fallback": "Mesure et incertitudes",
        "min_page": 6,
    },
    {
        "id": "constitution-matiere",
        "titre": ALLOWED_THEMES["constitution-matiere"],
        "type": "theme",
        "marker": " Constitution et transformations de la matière",
        "fallback": "Constitution et transformations de la matière",
        "min_page": 8,
    },
    {
        "id": "mouvement-interactions",
        "titre": ALLOWED_THEMES["mouvement-interactions"],
        "type": "theme",
        "marker": " Mouvement et interactions",
        "fallback": "Mouvement et interactions",
        "min_page": 19,
    },
    {
        "id": "energie-conversions",
        "titre": ALLOWED_THEMES["energie-conversions"],
        "type": "theme",
        "marker": " L’énergie : conversions et transferts",
        "fallback": "L’énergie : conversions et transferts",
        "min_page": 23,
    },
    {
        "id": "ondes-signaux",
        "titre": ALLOWED_THEMES["ondes-signaux"],
        "type": "theme",
        "marker": " Ondes et signaux",
        "fallback": "Ondes et signaux",
        "min_page": 25,
    },
    {
        "id": "capacites-experimentales",
        "titre": "Capacités expérimentales",
        "type": "capacites_experimentales",
        "marker": "Capacités expérimentales",
        "fallback": "Capacités expérimentales",
        "min_page": 31,
    },
]

ICONS = {
    "constitution-matiere": "⚗️",
    "mouvement-interactions": "🛰️",
    "energie-conversions": "🔥",
    "ondes-signaux": "🌊",
}

DESCRIPTIONS = {
    "constitution-matiere": "Analyse chimique, transformations acide-base, cinétique, radioactivité, équilibres, piles, électrolyse et synthèse organique.",
    "mouvement-interactions": "Cinématique vectorielle, deuxième loi de Newton, champs uniformes, gravitation, satellites, Kepler et dynamique des fluides.",
    "energie-conversions": "Gaz parfait, premier principe de la thermodynamique, transferts thermiques, bilan Terre-atmosphère et loi de Newton thermique.",
    "ondes-signaux": "Phénomènes ondulatoires, optique, photons, effet photoélectrique et dynamique du circuit RC.",
}


def resolve_programme_pdf(cli_pdf: str | None) -> Path:
    candidates: list[Path] = []
    if cli_pdf:
        candidates.append(Path(cli_pdf))
    candidates.append(PROGRAMME_PDF_PATH)
    candidates.extend(
        [
            SITE_ROOT / "programme" / "Terminale PC.pdf",
            SITE_ROOT / "pdf" / "Terminale PC.pdf",
            Path.cwd() / "Terminale PC.pdf",
            Path("/mnt/data/Terminale PC.pdf"),
        ]
    )
    for path in candidates:
        if path and path.exists():
            return path.resolve()
    raise FileNotFoundError(
        "Programme officiel introuvable. Fournir --pdf ou définir PROGRAMME_PDF_PATH, "
        "par exemple site/programme/Terminale PC.pdf."
    )


def extract_pages(pdf_path: Path) -> list[dict[str, Any]]:
    doc = fitz.open(pdf_path)
    pages = []
    for index, page in enumerate(doc, start=1):
        text = clean_pdf_text(page.get_text("text") or "")
        pages.append({"page": index, "text": text})
    return pages


def build_combined_text(pages: list[dict[str, Any]]) -> tuple[str, dict[int, int]]:
    chunks = []
    page_offsets: dict[int, int] = {}
    current = 0
    for page in pages:
        marker = f"\n\n<<<PAGE {int(page['page']):03d}>>>\n"
        chunks.append(marker)
        current += len(marker)
        page_offsets[int(page["page"])] = current
        txt = page.get("text", "")
        chunks.append(txt)
        current += len(txt)
    return "".join(chunks), page_offsets


def find_section_start(combined: str, page_offsets: dict[int, int], spec: dict[str, Any]) -> int:
    start_after = page_offsets.get(int(spec["min_page"]), 0)
    marker = spec["marker"]
    pos = combined.find(marker, start_after)
    if pos != -1:
        return pos

    # Recherche moins stricte : espaces et tirets variables, accents conservés.
    fallback = re.escape(spec["fallback"])
    pattern = re.compile(fallback, flags=re.I)
    match = pattern.search(combined, start_after)
    if match:
        return match.start()

    # Dernier recours : chercher après le sommaire, sinon signaler l'anomalie.
    match = pattern.search(combined)
    if match:
        return match.start()
    raise ValueError(f"Section introuvable : {spec['id']} / {spec['titre']}")


def page_for_pos(markers: list[tuple[int, int]], pos: int) -> int:
    current = markers[0][0] if markers else 1
    for page, marker_pos in markers:
        if marker_pos <= pos:
            current = page
        else:
            break
    return current


def split_sections(combined: str, page_offsets: dict[int, int]) -> list[dict[str, Any]]:
    starts = []
    for spec in SECTION_SPECS:
        pos = find_section_start(combined, page_offsets, spec)
        starts.append((pos, spec))
    starts.sort(key=lambda x: x[0])

    markers = [(int(m.group(1)), m.start()) for m in re.finditer(r"<<<PAGE (\d{3})>>>", combined)]

    sections = []
    for i, (pos, spec) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(combined)
        section_text = combined[pos:end]
        start_page = page_for_pos(markers, pos)
        end_page = page_for_pos(markers, max(pos, end - 1))
        page_numbers = list(range(start_page, end_page + 1))
        # On retire les marqueurs internes tout en conservant une indication de changement de page.
        text = re.sub(r"\n*<<<PAGE (\d{3})>>>\n*", r"\n\n[Page \1]\n", section_text).strip()
        sections.append(
            {
                "id": spec["id"],
                "titre": spec["titre"],
                "type": spec["type"],
                "pages": page_numbers,
                "texte": text,
                "char_count": len(text),
            }
        )
    return sections


def build_light_programme(raw_obj: dict[str, Any]) -> dict[str, Any]:
    sections = {s["id"]: s for s in raw_obj.get("sections", [])}
    thematiques = []
    for theme_id, titre in ALLOWED_THEMES.items():
        section = sections.get(theme_id, {})
        thematiques.append(
            {
                "id": theme_id,
                "titre": titre,
                "icone": ICONS.get(theme_id, ""),
                "description": DESCRIPTIONS.get(theme_id, ""),
                "programme_officiel": {
                    "section_id": theme_id,
                    "pages": section.get("pages", []),
                    "source": raw_obj.get("source", {}).get("pdf_name", ""),
                    "statut": "texte brut extrait — structuration à produire avec 00b_structure_programme_officiel.py",
                },
            }
        )
    return {
        "source": raw_obj.get("source", {}),
        "thematiques": thematiques,
        "transversal": {
            "mesure_incertitudes": {
                "section_id": "mesure-incertitudes",
                "pages": sections.get("mesure-incertitudes", {}).get("pages", []),
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrait le programme officiel de terminale PC en sections textuelles.")
    parser.add_argument("--pdf", type=str, default=None, help="Chemin vers le PDF officiel du programme.")
    parser.add_argument("--force", action="store_true", help="Réécrit les sorties existantes.")
    args = parser.parse_args()

    if PROGRAMME_OFFICIEL_RAW_JSON.exists() and not args.force:
        print(f"Déjà présent : {PROGRAMME_OFFICIEL_RAW_JSON} (--force pour régénérer)")
        return

    pdf_path = resolve_programme_pdf(args.pdf)
    ensure_dirs(DATA_DIR)
    pages = extract_pages(pdf_path)
    combined, page_offsets = build_combined_text(pages)
    sections = split_sections(combined, page_offsets)

    raw_obj = {
        "source": {
            "pdf_path": str(pdf_path),
            "pdf_name": pdf_path.name,
            "extracted_at": now_timestamp(),
            "pages_count": len(pages),
            "note": "Texte extrait automatiquement. La structuration fine est réalisée par 00b_structure_programme_officiel.py.",
        },
        "pages": pages,
        "sections": sections,
    }
    write_json(PROGRAMME_OFFICIEL_RAW_JSON, raw_obj)
    if not PROGRAMME_JSON.exists() or args.force:
        write_json(PROGRAMME_JSON, build_light_programme(raw_obj))

    print(f"Programme brut extrait : {PROGRAMME_OFFICIEL_RAW_JSON}")
    for section in sections:
        print(f"- {section['id']}: pages {section.get('pages')} — {section['char_count']} caractères")


if __name__ == "__main__":
    main()
