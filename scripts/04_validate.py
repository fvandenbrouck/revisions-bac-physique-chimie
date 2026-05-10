#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p.parent, *p.parents]:
        if (parent / "site").exists() and (parent / "scripts").exists():
            return parent
    return Path.cwd()


ROOT = find_project_root()
DATA = ROOT / "site" / "data"
RAW_DEFAULT = DATA / "intermediate" / "exercises_raw.json"
GENERATED_DIR_DEFAULT = DATA / "generated" / "exercises"
REPORTS = DATA / "rapports"

ALLOWED_THEMES = {
    "constitution-matiere",
    "mouvement-interactions",
    "energie-conversions",
    "ondes-signaux",
}

ALLOWED_DIFFICULTY = {1, 2, 3}


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def norm_qid(value: Any) -> str:
    """
    Normalise les numéros de questions :
    - Q1 -> 1
    - Question 1 -> 1
    - Partie A — 1 -> 1
    - partiea—9.1 -> 9.1
    - Problème à résoudre -> problème
    """
    s = str(value or "").strip().lower()

    # Uniformiser tirets et ponctuation
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    s = s.replace(":", "-")
    s = re.sub(r"\s+", "", s)

    # Supprimer préfixes fréquents
    s = s.replace("question", "")
    s = s.replace("q.", "q")
    s = re.sub(r"^q", "", s)

    # Supprimer "partiea-", "partie a-", "partieb-", etc.
    s = re.sub(r"^partie[a-z0-9]*[-_.]*", "", s)
    s = re.sub(r"^part\w*[-_.]*", "", s)

    # Si la chaîne contient un nombre après un préfixe, prendre le premier motif numérique.
    m = re.search(r"(\d+(?:[.,]\d+)*)", s)
    if m:
        s = m.group(1)

    s = s.replace(",", ".")
    s = s.strip(".:- ")

    aliases = {
        "probleme": "problème",
        "problem": "problème",
        "problemearesoudre": "problème",
        "problèmeàrésoudre": "problème",
        "problèmearesoudre": "problème",
    }
    return aliases.get(s, s)


def split_question_string(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [norm_qid(x) for x in value if norm_qid(x)]
    s = str(value)
    if not s.strip():
        return []
    parts = re.split(r"[;,|]", s)
    return [norm_qid(p) for p in parts if norm_qid(p)]


def corrige_question_ids(generated: dict[str, Any]) -> list[str]:
    corrige = generated.get("corrige") or {}
    questions = corrige.get("questions") if isinstance(corrige, dict) else None
    if not isinstance(questions, list):
        return []
    ids = []
    for q in questions:
        if isinstance(q, dict):
            qid = norm_qid(q.get("numero") or q.get("numéro") or q.get("question"))
            if qid:
                ids.append(qid)
    return ids


def qid_covers(expected: str, got: str) -> bool:
    expected = norm_qid(expected)
    got = norm_qid(got)

    if not expected or not got:
        return False
    if expected == got:
        return True

    # Une question attendue "1" est considérée couverte par "1.1", "1.2", etc.
    if expected.isdigit() and got.startswith(expected + "."):
        return True

    return False


def expected_covered(expected: str, got_ids: list[str]) -> bool:
    return any(qid_covers(expected, got) for got in got_ids)


def got_is_excess(got: str, expected_ids: list[str]) -> bool:
    return not any(qid_covers(exp, got) for exp in expected_ids)


def validate_exercise(raw: dict[str, Any], generated: dict[str, Any] | None) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    detail: dict[str, Any] = {}

    if generated is None:
        return ["generation_absente"], detail

    if generated.get("id") != raw.get("id"):
        errors.append("id_mismatch")

    if generated.get("thematique_id") not in ALLOWED_THEMES:
        errors.append("thematique_invalide")

    try:
        diff = int(generated.get("difficulte"))
        if diff not in ALLOWED_DIFFICULTY:
            errors.append("difficulte_invalide")
    except Exception:
        errors.append("difficulte_invalide")

    if not generated.get("titre"):
        errors.append("titre_absent")

    if not generated.get("page_images"):
        errors.append("page_images_absentes")

    if not generated.get("notions"):
        errors.append("notions_absentes")

    if not generated.get("mots_cles"):
        errors.append("mots_cles_absents")

    if not generated.get("aide"):
        errors.append("aide_absente")

    qs = generated.get("corrige", {}).get("questions", []) if isinstance(generated.get("corrige"), dict) else []
    if not isinstance(qs, list) or not qs:
        errors.append("corrige_absent")

    expected = split_question_string(raw.get("questions_detectees"))
    got = corrige_question_ids(generated)

    detail["questions_detectees"] = ",".join(expected)
    detail["questions_corrigees"] = ",".join(got)

    if expected and got:
        missing = [q for q in expected if not expected_covered(q, got)]
        excess = [q for q in got if got_is_excess(q, expected)]

        if missing:
            errors.append("questions_corrige_manquantes:" + ",".join(missing))
            detail["questions_manquantes"] = ",".join(missing)

        # Un excès de questions corrigées n'est pas bloquant :
        # il signifie souvent que Claude a détaillé des sous-questions
        # que le détecteur automatique n'avait pas repérées.
        # On le conserve dans le rapport, sans classer l'exercice à revoir.
        if excess:
            detail["questions_exces"] = ",".join(excess)

    empty_answers = []
    for q in qs if isinstance(qs, list) else []:
        if isinstance(q, dict) and len(str(q.get("reponse", "")).strip()) < 20:
            empty_answers.append(str(q.get("numero", "")))
    if empty_answers:
        errors.append("reponses_vides:" + ",".join(empty_answers[:10]))

    return errors, detail


def load_generated_by_id(generated_dir: Path) -> dict[str, dict[str, Any]]:
    out = {}
    if not generated_dir.exists():
        return out
    for p in generated_dir.glob("*.json"):
        data = read_json(p)
        if isinstance(data, dict) and data.get("id"):
            out[data["id"]] = data
    return out


def validate_courses() -> list[dict[str, Any]]:
    rows = []
    p = DATA / "cours.json"
    if not p.exists():
        rows.append({"fichier": str(p), "status": "a_revoir", "erreurs": "cours_absent"})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Validation assouplie des exercices générés.")
    parser.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    parser.add_argument("--generated-dir", type=Path, default=GENERATED_DIR_DEFAULT)
    args = parser.parse_args()

    raw_exercises = read_json(args.raw)
    if not isinstance(raw_exercises, list):
        raise RuntimeError(f"Fichier brut invalide : {args.raw}")

    generated_by_id = load_generated_by_id(args.generated_dir)

    rows: list[dict[str, Any]] = []
    summary = {
        "total_exercices_bruts": len(raw_exercises),
        "fichiers_generes": len(generated_by_id),
        "valides": 0,
        "a_revoir": 0,
        "erreurs_par_type": {},
    }
    err_counter = Counter()

    for raw in raw_exercises:
        ex_id = raw.get("id", "")
        gen = generated_by_id.get(ex_id)
        errors, detail = validate_exercise(raw, gen)

        status = "ok" if not errors else "a_revoir"
        if status == "ok":
            summary["valides"] += 1
        else:
            summary["a_revoir"] += 1
            for e in errors:
                err_counter[e.split(":")[0]] += 1

        rows.append(
            {
                "id": ex_id,
                "titre": (gen or raw).get("titre", ""),
                "source_id": raw.get("source_id", ""),
                "pages": "-".join(map(str, raw.get("pages", []))),
                "questions_detectees": detail.get("questions_detectees", ",".join(split_question_string(raw.get("questions_detectees")))),
                "questions_corrigees": detail.get("questions_corrigees", ""),
                "questions_manquantes": detail.get("questions_manquantes", ""),
                "questions_exces": detail.get("questions_exces", ""),
                "status": status,
                "erreurs": " | ".join(errors),
            }
        )

    summary["erreurs_par_type"] = dict(err_counter)
    course_errors = validate_courses()

    REPORTS.mkdir(parents=True, exist_ok=True)
    write_json(REPORTS / "validation.json", {"summary": summary, "exercices": rows, "cours": course_errors})
    write_csv(
        REPORTS / "validation.csv",
        rows,
        [
            "id",
            "titre",
            "source_id",
            "pages",
            "questions_detectees",
            "questions_corrigees",
            "questions_manquantes",
            "questions_exces",
            "status",
            "erreurs",
        ],
    )
    write_csv(REPORTS / "validation_cours.csv", course_errors, ["fichier", "status", "erreurs"])

    print("Rapport JSON :", REPORTS / "validation.json")
    print("Rapport CSV  :", REPORTS / "validation.csv")
    print("Cours CSV    :", REPORTS / "validation_cours.csv")
    print(summary)


if __name__ == "__main__":
    main()
