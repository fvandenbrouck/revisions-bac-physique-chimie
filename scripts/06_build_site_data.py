#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p.parent, *p.parents]:
        if (parent / "site").exists() and (parent / "scripts").exists():
            return parent
    return Path.cwd()


ROOT = find_project_root()
SITE = ROOT / "site"
DATA = SITE / "data"

PROGRAMME_PATH = DATA / "programme.json"
PROGRAMME_OFFICIEL_PATH = DATA / "programme_officiel.json"
COURS_PATH = DATA / "cours.json"
QUIZ_PATH = DATA / "quiz.json"

# Source canonique : les fichiers individuels validés.
GENERATED_EXERCISES_DIR = DATA / "generated" / "exercises"

# Sorties
EXERCICES_JSON = DATA / "exercices.json"
DATA_JSON = DATA / "data.json"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_corrige(corrige: Any) -> dict[str, Any]:
    if isinstance(corrige, dict):
        qs = corrige.get("questions")
        if isinstance(qs, list):
            return corrige
        # Dict sans clé questions : conversion prudente.
        questions = []
        for k, v in corrige.items():
            if isinstance(v, dict):
                item = {"numero": str(k)}
                item.update(v)
                questions.append(item)
            else:
                questions.append({"numero": str(k), "reponse": str(v), "points_attention": ""})
        return {"questions": questions}

    if isinstance(corrige, list):
        return {"questions": corrige}

    if isinstance(corrige, str):
        return {
            "questions": [
                {
                    "numero": "global",
                    "reponse": corrige,
                    "points_attention": "",
                }
            ]
        }

    return {"questions": []}


def normalize_exercise(ex: dict[str, Any]) -> dict[str, Any]:
    out = dict(ex)

    # Compatibilité frontend : garantir toujours les champs structurants.
    out.setdefault("id", "")
    out.setdefault("titre", "")
    out.setdefault("annee", "")
    out.setdefault("session", "")
    out.setdefault("zone", "")
    out.setdefault("thematique_id", "")
    out.setdefault("notions", [])
    out.setdefault("mots_cles", [])
    out.setdefault("difficulte", "")
    out.setdefault("aide", [])
    out.setdefault("pages", [])
    out.setdefault("page_images", [])

    if out.get("page_images") is None:
        out["page_images"] = []
    if out.get("notions") is None:
        out["notions"] = []
    if out.get("mots_cles") is None:
        out["mots_cles"] = []
    if out.get("aide") is None:
        out["aide"] = []

    out["corrige"] = normalize_corrige(out.get("corrige"))

    # Ancienne interface : certains index.html attendent image_page.
    if not out.get("image_page"):
        imgs = out.get("page_images") or []
        out["image_page"] = imgs[0] if imgs else ""

    return out


def load_generated_exercises() -> list[dict[str, Any]]:
    if not GENERATED_EXERCISES_DIR.exists():
        raise FileNotFoundError(f"Dossier d'exercices générés introuvable : {GENERATED_EXERCISES_DIR}")

    exercises: list[dict[str, Any]] = []
    for p in sorted(GENERATED_EXERCISES_DIR.glob("*.json")):
        obj = read_json(p)
        if not isinstance(obj, dict):
            print(f"Ignore fichier non-dict : {p}")
            continue
        if not obj.get("id"):
            print(f"Ignore exercice sans id : {p}")
            continue
        exercises.append(normalize_exercise(obj))

    return exercises


def sort_key(ex: dict[str, Any]) -> tuple:
    return (
        str(ex.get("annee", "")),
        str(ex.get("zone", "")),
        str(ex.get("session", "")),
        str(ex.get("source_id", "")),
        str(ex.get("type", "")),
        str(ex.get("id", "")),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Construit site/data/exercices.json et site/data/data.json depuis les JSON individuels validés.")
    parser.add_argument("--force", action="store_true", help="Accepté pour compatibilité ; les sorties sont toujours réécrites.")
    args = parser.parse_args()

    exercices = load_generated_exercises()
    exercices.sort(key=sort_key)

    programme = read_json(PROGRAMME_PATH, default={})
    programme_officiel = read_json(PROGRAMME_OFFICIEL_PATH, default={})
    cours = read_json(COURS_PATH, default={})
    quiz = read_json(QUIZ_PATH, default=[])

    payload = {
        "programme": programme,
        "programme_officiel": programme_officiel,
        "exercices": exercices,
        "cours": cours,
        "quiz": quiz,
    }

    write_json(EXERCICES_JSON, exercices)
    write_json(DATA_JSON, payload)

    print(f"Exercices écrits : {EXERCICES_JSON} ({len(exercices)})")
    print(f"Data site écrit  : {DATA_JSON}")
    print(f"Cours            : {len(cours) if isinstance(cours, dict) else type(cours).__name__}")
    print(f"Programme officiel : {'OK' if programme_officiel else 'absent'}")

    # Contrôles simples
    bad_corrige = [ex["id"] for ex in exercices if not isinstance(ex.get("corrige"), dict)]
    no_images = [ex["id"] for ex in exercices if not ex.get("page_images")]

    print(f"Corrigés non structurés : {len(bad_corrige)}")
    print(f"Exercices sans images   : {len(no_images)}")

    if bad_corrige:
        print("Exemples corrigés non structurés :", bad_corrige[:5])
    if no_images:
        print("Exemples sans images :", no_images[:5])


if __name__ == "__main__":
    main()
