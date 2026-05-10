#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from config import EXERCISES_RAW_JSON, MANIFEST_CSV, PAGES_DIR, REPORTS_DIR
from utils import detect_question_ids, normalize_space, read_csv_dicts, read_json, write_json


# ---------------------------------------------------------------------------
# Objectif
# ---------------------------------------------------------------------------
# Segmenter les sujets en exercices sans sur-découper.
#
# Correction principale par rapport à l’ancienne version :
# - les marqueurs doivent être en début de ligne ;
# - les consignes du type « exercices au choix », « exercice A ou exercice B »
#   sont ignorées ;
# - les formats récents avec EXERCICE 1 / 2 / 3 ou EXERCICE I / II / III sont gérés ;
# - les formats anciens avec exercice commun + EXERCICE A/B/C sont gérés ;
# - un même exercice ne peut pas être détecté 5 fois : on garde le premier
#   marqueur pertinent par type.
# ---------------------------------------------------------------------------


EXCLUSION_RE = re.compile(
    r"("
    r"exercices?\s+au\s+choix|"
    r"vous\s+indiquerez|"
    r"exercices?\s+choisis?|"
    r"choisir\s+2\s+exercices|"
    r"parmi\s+les\s+3|"
    r"le\s+candidat\s+traite|"
    r"l[’']exercice\s+1\s+puis|"
    r"exercice\s+a\s+ou\s+exercice\s+b|"
    r"exercice\s+b\s+ou\s+exercice\s+c"
    r")",
    re.IGNORECASE,
)

# Préfixes fréquents ajoutés par l'extraction de texte :
# « 21-PYCJ1G11 Page 2/15 EXERCICE 1 ... »
PAGE_PREFIX_RE = re.compile(
    r"^\s*"
    r"(?:\d{2}\s*[- ]?\s*PYC[A-Z0-9\- ]{0,20}\s+)?"
    r"(?:Page\s+\d+\s*/\s*\d+\s*)?",
    re.IGNORECASE,
)

MARKER_RE = re.compile(
    r"^\s*"
    r"(?:EXERCICE|Exercice)\s+"
    r"("
    r"commun(?:\s+à\s+tous\s+les\s+candidats)?|"
    r"[1-9]|"
    r"IV|III|II|I|V|"
    r"[ABC]"
    r")"
    r"\b"
    r"(?P<rest>.*)$",
    re.IGNORECASE,
)

ROMAN_TO_INT = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
}

POINTS_RE = re.compile(r"\((\d{1,2})\s*points?\)", re.IGNORECASE)


def enabled(row: dict[str, str]) -> bool:
    return str(row.get("enabled", "1")).strip().lower() not in {"0", "false", "non", "no"}


def clean_marker_line(line: str) -> str:
    line = normalize_space(line or "")
    line = PAGE_PREFIX_RE.sub("", line).strip()
    line = re.sub(r"^\s*[-–—:]+\s*", "", line)
    return line


def parse_marker(line: str, page_no: int, line_index: int) -> dict[str, Any] | None:
    original = line
    line = clean_marker_line(line)

    if not line:
        return None

    # Évite les lignes de consigne.
    if EXCLUSION_RE.search(line):
        return None

    # Ligne trop longue : souvent phrase de consigne contenant « exercice A ».
    if len(line) > 230:
        return None

    m = MARKER_RE.match(line)
    if not m:
        return None

    token = m.group(1).strip()
    token_upper = token.upper()
    rest = (m.group("rest") or "").strip()

    # Exclusion de sécurité : « Exercice A ou exercice B » après retour à la ligne.
    if re.search(r"\bou\s+exercice\s+[ABC]\b", rest, flags=re.IGNORECASE):
        return None

    if token_upper.startswith("COMMUN"):
        kind = "commun"
        key = "commun"
        ex_type = "commun"
        number = None
    elif token_upper in {"A", "B", "C"}:
        kind = "letter"
        key = token_upper
        ex_type = token_upper
        number = None
    elif token_upper.isdigit() or token_upper in ROMAN_TO_INT:
        number = int(token_upper) if token_upper.isdigit() else ROMAN_TO_INT[token_upper]
        kind = "number"
        key = f"N{number}"
        # Si l'énoncé dit explicitement commun, c'est le format ancien.
        if number == 1 and re.search(r"\bcommun\b", line, flags=re.IGNORECASE):
            ex_type = "commun"
        else:
            ex_type = str(number)
    else:
        return None

    return {
        "page": page_no,
        "line_index": line_index,
        "line": original,
        "label": line,
        "kind": kind,
        "key": key,
        "type": ex_type,
        "number": number,
    }


def find_candidates(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for p in pages:
        page_no = int(p.get("page", 0))
        text = p.get("text", "") or ""
        lines = [line.rstrip() for line in text.splitlines()]

        for idx, line in enumerate(lines):
            marker = parse_marker(line, page_no, idx)
            if marker:
                candidates.append(marker)

    # Déduplication stricte : même page, même ligne nettoyée.
    seen = set()
    deduped = []
    for c in candidates:
        sig = (c["page"], c["line_index"], c["label"].lower())
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(c)

    deduped.sort(key=lambda x: (x["page"], x["line_index"]))
    return deduped


def choose_segmentation_mode(candidates: list[dict[str, Any]]) -> str:
    has_letters = any(c["kind"] == "letter" for c in candidates)
    numbers = sorted({c["number"] for c in candidates if c["kind"] == "number" and c["number"] is not None})

    if has_letters:
        return "legacy_common_abc"

    # Format récent : exercices numérotés.
    if any(n >= 2 for n in numbers):
        return "numbered"

    # Format minimal ou mal détecté.
    return "single_or_common"


def select_starts(candidates: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    mode = choose_segmentation_mode(candidates)

    if mode == "legacy_common_abc":
        wanted_order = ["commun", "A", "B", "C"]
        selected_by_key: dict[str, dict[str, Any]] = {}

        for c in candidates:
            key = None

            if c["kind"] == "letter" and c["key"] in {"A", "B", "C"}:
                key = c["key"]
            elif c["kind"] == "commun":
                key = "commun"
            elif c["kind"] == "number" and c.get("number") == 1:
                key = "commun"

            if key and key not in selected_by_key:
                selected = dict(c)
                selected["selected_key"] = key
                selected["type"] = "commun" if key == "commun" else key
                selected_by_key[key] = selected

        selected = [selected_by_key[k] for k in wanted_order if k in selected_by_key]
        selected.sort(key=lambda x: (x["page"], x["line_index"]))
        return mode, selected

    if mode == "numbered":
        selected_by_number: dict[int, dict[str, Any]] = {}

        for c in candidates:
            if c["kind"] != "number" or c.get("number") is None:
                continue
            n = int(c["number"])
            # On accepte 1 à 9, mais les sujets attendus sont en général 1 à 3.
            if not (1 <= n <= 9):
                continue
            if n not in selected_by_number:
                selected = dict(c)
                selected["selected_key"] = f"N{n}"
                selected["type"] = str(n)
                selected_by_number[n] = selected

        selected = [selected_by_number[n] for n in sorted(selected_by_number)]
        selected.sort(key=lambda x: (x["page"], x["line_index"]))
        return mode, selected

    # Repli : premier marqueur commun ou exercice 1.
    for c in candidates:
        if c["kind"] == "commun" or (c["kind"] == "number" and c.get("number") == 1):
            selected = dict(c)
            selected["selected_key"] = "commun"
            selected["type"] = "commun"
            return mode, [selected]

    return mode, []


def infer_points(label: str, ex_type: str) -> int | str:
    m = POINTS_RE.search(label or "")
    if m:
        return int(m.group(1))
    if ex_type == "commun":
        return 10
    if ex_type in {"A", "B", "C", "2", "3", "4"}:
        return 5
    return ""


def strip_exercise_label(label: str) -> str:
    s = label or ""
    s = POINTS_RE.sub("", s)
    s = re.sub(
        r"^(?:EXERCICE|Exercice)\s+(?:commun(?:\s+à\s+tous\s+les\s+candidats)?|[1-9]|IV|III|II|I|V|[ABC])\b",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"^[\s:;.,\-–—]+", "", s)
    return normalize_space(s)


def is_probable_title_line(line: str) -> bool:
    line = clean_marker_line(line)
    if not line:
        return False
    if len(line) < 5 or len(line) > 150:
        return False

    bad = [
        "données",
        "mots-clés",
        "mots clés",
        "questions",
        "le candidat",
        "vous indiquerez",
        "figure",
        "annexe",
        "page ",
        "durée de l’épreuve",
        "l’usage de la calculatrice",
    ]
    low = line.lower()
    if any(b in low for b in bad):
        return False

    if MARKER_RE.match(line):
        return False

    # Titre souvent en capitales, mais pas toujours.
    has_letters = bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", line))
    return has_letters


def infer_title(start_label: str, exercise_text: str) -> str:
    from_label = strip_exercise_label(start_label)
    if 5 <= len(from_label) <= 150:
        return from_label

    lines = [l.strip() for l in (exercise_text or "").splitlines() if l.strip()]
    for line in lines[:25]:
        cleaned = strip_exercise_label(clean_marker_line(line))
        cleaned = POINTS_RE.sub("", cleaned).strip()
        if is_probable_title_line(cleaned):
            return cleaned[:160]

    return "Exercice sans titre détecté"


def slice_lines(lines: list[str], start: int | None = None, end: int | None = None) -> str:
    s = 0 if start is None else max(0, start)
    e = len(lines) if end is None else max(0, end)
    return "\n".join(lines[s:e])


def build_exercise_text(
    pages_by_no: dict[int, dict[str, Any]],
    start_marker: dict[str, Any],
    next_marker: dict[str, Any] | None,
) -> tuple[list[int], list[str], str]:
    start_page = int(start_marker["page"])
    end_page = int(next_marker["page"]) if next_marker else max(pages_by_no)
    page_numbers = list(range(start_page, end_page + 1))

    parts: list[str] = []
    images: list[str] = []

    for page_no in page_numbers:
        page = pages_by_no.get(page_no)
        if not page:
            continue

        lines = (page.get("text", "") or "").splitlines()
        start_idx = None
        end_idx = None

        if page_no == start_page:
            start_idx = int(start_marker["line_index"])

        if next_marker and page_no == int(next_marker["page"]):
            end_idx = int(next_marker["line_index"])

        chunk = slice_lines(lines, start_idx, end_idx)
        if chunk.strip():
            parts.append(chunk)

        img = page.get("image")
        if img:
            images.append(img)

    # Si deux exercices commencent sur la même page, la page image est partagée ;
    # c'est normal, mais on ne duplique pas les chemins.
    unique_images = []
    for img in images:
        if img not in unique_images:
            unique_images.append(img)

    text = normalize_space("\n\n".join(parts))
    selected_pages = [p for p in page_numbers if p in pages_by_no]
    return selected_pages, unique_images, text


def segment_one(source: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_id = source["source_id"]
    pages = source.get("pages", [])
    pages_by_no = {int(p["page"]): p for p in pages}

    candidates = find_candidates(pages)
    mode, starts = select_starts(candidates)

    diagnostic = {
        "source_id": source_id,
        "page_count": len(pages),
        "candidates": len(candidates),
        "selected": len(starts),
        "mode": mode,
        "candidate_labels": [c["label"] for c in candidates[:30]],
        "selected_labels": [s["label"] for s in starts],
    }

    exercises: list[dict[str, Any]] = []

    if not starts:
        full_text = normalize_space("\n\n".join(p.get("text", "") for p in pages))
        exercises.append(
            {
                "id": f"ex-{source_id}-full",
                "source_id": source_id,
                "annee": source.get("annee", ""),
                "session": source.get("session", ""),
                "zone": source.get("zone", ""),
                "titre": source.get("titre", "Sujet complet non segmenté"),
                "type": "à découper",
                "points": "",
                "pages": [p["page"] for p in pages],
                "page_images": [p["image"] for p in pages if p.get("image")],
                "texte_extrait": full_text,
                "questions_detectees": detect_question_ids(full_text),
                "segmentation_warning": "Aucun début d'exercice détecté automatiquement.",
                "segmentation_mode": mode,
            }
        )
        diagnostic["warning"] = "Aucun début d'exercice détecté."
        return exercises, diagnostic

    for i, start in enumerate(starts):
        next_marker = starts[i + 1] if i + 1 < len(starts) else None
        selected_pages, page_images, exercise_text = build_exercise_text(pages_by_no, start, next_marker)

        ex_type = start["type"]
        if ex_type == "commun":
            suffix = "commun"
        elif ex_type in {"A", "B", "C"}:
            suffix = f"exercice-{ex_type.lower()}"
        elif str(ex_type).isdigit():
            suffix = f"exercice-{ex_type}"
        else:
            suffix = f"exercice-{i + 1}"

        title = infer_title(start["label"], exercise_text)
        ex_id = f"ex-{source_id}-{suffix}"

        exercises.append(
            {
                "id": ex_id,
                "source_id": source_id,
                "annee": source.get("annee", ""),
                "session": source.get("session", ""),
                "zone": source.get("zone", ""),
                "titre": title,
                "type": ex_type,
                "points": infer_points(start["label"], ex_type),
                "pages": selected_pages,
                "page_images": page_images,
                "texte_extrait": exercise_text,
                "questions_detectees": detect_question_ids(exercise_text),
                "start_label": start["label"],
                "segmentation_mode": mode,
            }
        )

    # Avertissements simples.
    if mode == "legacy_common_abc":
        expected = {"commun", "A", "B", "C"}
        got = {ex["type"] for ex in exercises}
        missing = sorted(expected - got)
        if missing:
            diagnostic["warning"] = "Segments attendus manquants : " + ", ".join(missing)
    elif mode == "numbered":
        nums = [int(ex["type"]) for ex in exercises if str(ex["type"]).isdigit()]
        if nums and nums != list(range(min(nums), max(nums) + 1)):
            diagnostic["warning"] = f"Numérotation discontinue : {nums}"

    return exercises, diagnostic


def write_report(diagnostics: list[dict[str, Any]], all_exercises: list[dict[str, Any]]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Rapport JSON complet.
    write_json(REPORTS_DIR / "segmentation_diagnostic.json", diagnostics)

    # Rapport CSV compact.
    csv_path = REPORTS_DIR / "segmentation_diagnostic.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "source_id",
            "mode",
            "page_count",
            "candidates",
            "selected",
            "selected_labels",
            "warning",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in diagnostics:
            writer.writerow(
                {
                    "source_id": d.get("source_id"),
                    "mode": d.get("mode"),
                    "page_count": d.get("page_count"),
                    "candidates": d.get("candidates"),
                    "selected": d.get("selected"),
                    "selected_labels": " | ".join(d.get("selected_labels", [])),
                    "warning": d.get("warning", ""),
                }
            )

    # Rapport par source.
    by_source = defaultdict(list)
    for ex in all_exercises:
        by_source[ex["source_id"]].append(ex)

    count_path = REPORTS_DIR / "segmentation_counts.csv"
    with count_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["source_id", "nb_exercices", "types", "pages", "titres"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for source_id, exercises in sorted(by_source.items()):
            writer.writerow(
                {
                    "source_id": source_id,
                    "nb_exercices": len(exercises),
                    "types": " | ".join(str(e.get("type", "")) for e in exercises),
                    "pages": " | ".join("-".join(map(str, e.get("pages", []))) for e in exercises),
                    "titres": " | ".join(str(e.get("titre", ""))[:80] for e in exercises),
                }
            )

    print(f"Rapport segmentation : {csv_path}")
    print(f"Comptage par sujet   : {count_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Découpe les textes extraits en exercices bruts, sans sur-segmentation.")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_CSV)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true", help="Accepté pour compatibilité ; le fichier de sortie est toujours réécrit.")
    args = parser.parse_args()

    rows = [r for r in read_csv_dicts(args.manifest) if enabled(r)]
    if args.limit:
        rows = rows[: args.limit]

    if not rows:
        print("Aucun sujet activé dans le manifest.", file=sys.stderr)
        sys.exit(1)

    all_exercises: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    missing = []

    for idx, row in enumerate(rows, start=1):
        source_id = row["id"]
        page_file = PAGES_DIR / f"{source_id}.json"

        source = read_json(page_file)
        if not source:
            missing.append(source_id)
            continue

        exercises, diagnostic = segment_one(source)
        all_exercises.extend(exercises)
        diagnostics.append(diagnostic)

        print(
            f"[{idx:03d}/{len(rows):03d}] {source_id}: "
            f"{len(exercises)} exercice(s), mode={diagnostic.get('mode')}, "
            f"candidats={diagnostic.get('candidates')}, sélection={diagnostic.get('selected')}"
        )

    write_json(EXERCISES_RAW_JSON, all_exercises)
    write_report(diagnostics, all_exercises)

    counts = Counter(ex["source_id"] for ex in all_exercises)
    distribution = Counter(counts.values())

    print(f"\nExercices bruts générés : {len(all_exercises)} -> {EXERCISES_RAW_JSON}")
    print("Distribution du nombre d'exercices par sujet :")
    for n in sorted(distribution):
        print(f"  {n} exercice(s): {distribution[n]} sujet(s)")

    suspicious = [sid for sid, count in counts.items() if count not in {3, 4}]
    print(f"Sujets avec un nombre d'exercices différent de 3 ou 4 : {len(suspicious)}")
    for sid in suspicious[:20]:
        print(f"  - {sid}: {counts[sid]} exercice(s)")

    if missing:
        print(f"\nAttention : extraction pages absente pour {len(missing)} sujet(s): {', '.join(missing[:10])}", file=sys.stderr)


if __name__ == "__main__":
    main()
