#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from config import ALLOWED_THEMES, COURSES_JSON
from utils import read_json, write_json


def escape_label(label: str) -> str:
    label = str(label).replace('"', "'").replace("\n", " ")
    label = re.sub(r"\s+", " ", label).strip()
    return label[:90]


def safe_mermaid_from_struct(carte: dict[str, Any], title: str) -> str:
    lines = ["graph TD", f'ROOT["{escape_label(title)}"]']
    branches = carte.get("branches") or []
    for i, b in enumerate(branches[:8], start=1):
        bid = f"B{i}"
        lines.append(f'ROOT --> {bid}["{escape_label(b.get("nom", f"Branche {i}"))}"]')
        for j, item in enumerate((b.get("items") or [])[:8], start=1):
            lines.append(f'{bid} --> I{i}_{j}["{escape_label(item)}"]')
    return "\n".join(lines)


def fallback_struct(course: dict[str, Any], theme_id: str) -> dict[str, Any]:
    title = course.get("titre") or ALLOWED_THEMES.get(theme_id, theme_id)
    definitions = [d.get("terme") for d in course.get("definitions", []) if isinstance(d, dict) and d.get("terme")]
    formules = [f.get("nom") for f in course.get("formules", []) if isinstance(f, dict) and f.get("nom")]
    conseils = [str(c)[:70] for c in course.get("conseils_bac", []) if c]
    branches = []
    if definitions:
        branches.append({"nom": "Notions", "items": definitions[:8]})
    if formules:
        branches.append({"nom": "Formules", "items": formules[:8]})
    if conseils:
        branches.append({"nom": "Méthode bac", "items": conseils[:8]})
    if not branches:
        branches = [{"nom": "Réviser", "items": ["Comprendre les grandeurs", "Identifier les unités", "Justifier les lois utilisées"]}]
    return {"titre": title, "branches": branches}


def main() -> None:
    parser = argparse.ArgumentParser(description="Répare les cartes Mermaid de cours.json en les régénérant avec des identifiants sûrs.")
    parser.add_argument("--file", type=Path, default=COURSES_JSON)
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()

    courses = read_json(args.file, default={})
    if not isinstance(courses, dict):
        raise SystemExit("cours.json doit contenir un objet indexé par thematique_id.")

    if args.backup and args.file.exists():
        backup = args.file.with_suffix(args.file.suffix + ".bak")
        backup.write_text(args.file.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Sauvegarde : {backup}")

    count = 0
    for theme_id, course in courses.items():
        if not isinstance(course, dict):
            continue
        carte = course.get("carte_mentale")
        if not isinstance(carte, dict):
            carte = fallback_struct(course, theme_id)
            course["carte_mentale"] = carte
        title = course.get("titre") or ALLOWED_THEMES.get(theme_id, theme_id)
        course["carte_mentale_mermaid"] = safe_mermaid_from_struct(carte, title)
        count += 1

    write_json(args.file, courses)
    print(f"Cartes Mermaid réparées : {count} -> {args.file}")


if __name__ == "__main__":
    main()
