#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
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
MANIFEST_JSON_PATH = DATA / "manifest.json"

# Source canonique : les fichiers individuels validés.
GENERATED_EXERCISES_DIR = DATA / "generated" / "exercises"

# Sorties
EXERCICES_JSON = DATA / "exercices.json"
DATA_JSON = DATA / "data.json"

MANUAL_SOURCE_PDF_ALIASES = {
    "2021-jour-1-po-physique-chimie-baccalaureat-generalj1-21-pycj1po1pdf-9":
        "pdf/physique-chimie-baccalaureat-generalj1-21-pycj1po1pdf-91125.pdf",

    "2022-jour-1-lr-baccalaur-g-n-ral-2022-physique-chimie-mayotte-santorin":
        "pdf/baccalaur-g-n-ral-2022-physique-chimie-mayotte-santorin-jour-1-114668pdf-96066.pdf",

    "2022-jour-2-lr-baccalaur-g-n-ral-2022-physique-chimie-mayotte-santorin":
        "pdf/baccalaur-g-n-ral-2022-physique-chimie-mayotte-santorin-jour-2-114671pdf-96069.pdf",

    "2022-jour-2-me-baccalaur-g-n-ral-2022-physique-chimie-preuve-du-12-mai":
        "pdf/baccalaur-g-n-ral-2022-physique-chimie-preuve-du-12-mai-2022-114347pdf-96405.pdf",

    "2022-jour-1-po-baccalaur-g-n-ral-2022-physique-chimie-pf-1-114761pdf-9":
        "pdf/baccalaur-g-n-ral-2022-physique-chimie-pf-1-114761pdf-96285.pdf",

    "2022-jour-2-po-baccalaur-g-n-ral-2022-physique-chimie-pf-2-114764pdf-9":
        "pdf/baccalaur-g-n-ral-2022-physique-chimie-pf-2-114764pdf-96288.pdf",
}



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



def normalize_pdf_path_for_site(value: Any) -> str:
    """Normalise un chemin PDF pour le site publié depuis le dossier site/."""
    value = str(value or "").strip()
    if not value:
        return ""
    value = value.replace("\\", "/")
    value = value.replace("site/", "")
    value = value.replace("./", "")
    value = value.lstrip("/")

    if not value.startswith("pdf/"):
        name = value.split("/")[-1]
        if name.lower().endswith(".pdf"):
            value = "pdf/" + name

    return value


def pdf_match_key(value: Any) -> str:
    """Clé de rapprochement robuste : minuscules, lettres/chiffres seulement."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def attach_pdf_paths_to_exercises(exercices: list[dict[str, Any]]) -> int:
    """Ajoute pdf_path aux exercices à partir du manifest.

    Le manifest et les exercices n'utilisent pas exactement les mêmes identifiants :
    - manifest : 2021-jour1-21-pycj1g1pdf-91416
    - exercices : 2021-jour-1-g1-21-pycj1g1pdf-91416

    On tente donc :
    1. une correspondance exacte ;
    2. une correspondance normalisée ;
    3. une correspondance par fragment de nom de PDF.
    """
    manifest = read_json(MANIFEST_JSON_PATH, default=[])

    if isinstance(manifest, dict):
        manifest_rows = list(manifest.values())
    elif isinstance(manifest, list):
        manifest_rows = manifest
    else:
        manifest_rows = []

    exact: dict[str, dict[str, Any]] = {}
    candidates: list[tuple[str, dict[str, Any]]] = []

    for row in manifest_rows:
        if not isinstance(row, dict):
            continue

        raw_id = str(row.get("id") or row.get("source_id") or "").strip()
        pdf_path = normalize_pdf_path_for_site(row.get("pdf_path") or row.get("pdf") or "")
        pdf_stem = Path(pdf_path).stem if pdf_path else ""

        aliases = {
            raw_id,
            raw_id.replace("jour1", "jour-1").replace("jour2", "jour-2"),
            pdf_stem,
        }

        for alias in aliases:
            alias = str(alias or "").strip()
            if not alias:
                continue
            exact[alias] = row
            key = pdf_match_key(alias)
            if key:
                candidates.append((key, row))

    patched = 0

    for ex in exercices:
        if not isinstance(ex, dict):
            continue

        sid = str(ex.get("source_id") or ex.get("sujet_id") or "").strip()
        row = exact.get(sid)

        sid_key = pdf_match_key(sid)

        if row is None and sid_key:
            for key, candidate in candidates:
                if key and (key in sid_key or sid_key in key):
                    row = candidate
                    break

        if row:
            pdf = normalize_pdf_path_for_site(row.get("pdf_path") or row.get("pdf") or "")
        else:
            pdf = normalize_pdf_path_for_site(MANUAL_SOURCE_PDF_ALIASES.get(sid, ""))

        if pdf:
            ex["pdf_path"] = pdf
            patched += 1

    return patched

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
    pdf_patched = attach_pdf_paths_to_exercises(exercices)

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
    print(f"PDF rattachés       : {pdf_patched}")

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
