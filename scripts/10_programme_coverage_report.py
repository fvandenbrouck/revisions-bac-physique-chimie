#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from typing import Any

from config import COURSES_JSON, PROGRAMME_COVERAGE_JSON, PROGRAMME_OFFICIEL_JSON, REPORTS_DIR
from utils import read_json, write_json


def iter_programme_blocks(programme: dict[str, Any]):
    for theme in programme.get("themes", []) or []:
        theme_id = theme.get("id")
        theme_title = theme.get("titre")
        for part in theme.get("sous_parties", []) or []:
            part_title = part.get("titre")
            for block in part.get("blocs", []) or []:
                yield {
                    "theme_id": theme_id,
                    "theme_title": theme_title,
                    "part_title": part_title,
                    "bloc_id": block.get("id"),
                    "notions": " ; ".join(block.get("notions_contenus", []) or []),
                    "capacites": " ; ".join(block.get("capacites_exigibles", []) or []),
                }


def course_coverage_map(courses: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for theme_id, course in courses.items():
        if not isinstance(course, dict):
            continue
        for item in course.get("couverture_programme", []) or []:
            bid = str(item.get("bloc_id", "")).strip()
            if bid:
                out[bid] = {
                    "theme_id": theme_id,
                    "statut": str(item.get("statut", "")),
                    "ou": str(item.get("ou", "")),
                }
        for module in course.get("modules", []) or []:
            for bid in module.get("bloc_ids_programme", []) or []:
                bid = str(bid).strip()
                if bid and bid not in out:
                    out[bid] = {"theme_id": theme_id, "statut": "couvert", "ou": str(module.get("titre", ""))}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Produit un rapport de couverture programme -> cours.")
    parser.parse_args()

    programme = read_json(PROGRAMME_OFFICIEL_JSON, default={}) or {}
    courses = read_json(COURSES_JSON, default={}) or {}
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    coverage = course_coverage_map(courses)
    rows = []
    summary = {"total_blocs": 0, "couverts": 0, "manquants": 0, "par_theme": {}}
    for block in iter_programme_blocks(programme):
        bid = str(block.get("bloc_id", ""))
        cov = coverage.get(bid)
        status = "couvert" if cov else "manquant"
        theme_id = block.get("theme_id")
        summary["total_blocs"] += 1
        summary["par_theme"].setdefault(theme_id, {"total": 0, "couverts": 0, "manquants": 0})
        summary["par_theme"][theme_id]["total"] += 1
        if cov:
            summary["couverts"] += 1
            summary["par_theme"][theme_id]["couverts"] += 1
        else:
            summary["manquants"] += 1
            summary["par_theme"][theme_id]["manquants"] += 1
        rows.append({**block, "status": status, "ou": (cov or {}).get("ou", "")})

    write_json(PROGRAMME_COVERAGE_JSON, {"summary": summary, "rows": rows})
    csv_path = REPORTS_DIR / "programme_coverage.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["theme_id", "theme_title", "part_title", "bloc_id", "status", "ou", "notions", "capacites"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Rapport programme JSON : {PROGRAMME_COVERAGE_JSON}")
    print(f"Rapport programme CSV  : {csv_path}")
    print(summary)


if __name__ == "__main__":
    main()
