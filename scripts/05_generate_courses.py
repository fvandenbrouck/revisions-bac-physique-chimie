#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    import anthropic
except Exception:
    print("ERREUR : module anthropic absent. Lance : python -m pip install anthropic python-dotenv")
    raise


def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p.parent, *p.parents]:
        if (parent / "site").exists() and (parent / "scripts").exists():
            return parent
    return Path.cwd()


ROOT = find_project_root()
SITE = ROOT / "site"
DATA = SITE / "data"

PROGRAMME_PATH_CANDIDATES = [
    DATA / "programme_officiel.json",
    DATA / "generated" / "programme_officiel.json",
]
EXERCISES_PATH_CANDIDATES = [
    DATA / "exercices.json",
    DATA / "generated" / "exercices.json",
]
OUT_COURS = DATA / "cours.json"
OUT_COURS_GENERATED = DATA / "generated" / "cours.json"
REPORTS = DATA / "rapports"

if load_dotenv:
    load_dotenv(ROOT / ".env")

DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS_COURSE", os.getenv("CLAUDE_MAX_TOKENS", "64000")))
DEFAULT_TEMPERATURE = float(os.getenv("CLAUDE_TEMPERATURE", "0.1"))

THEME_ORDER = [
    "mesure-incertitudes",
    "constitution-matiere",
    "mouvement-interactions",
    "energie-conversions",
    "ondes-signaux",
]

THEME_LABELS = {
    "mesure-incertitudes": "Mesure et incertitudes",
    "constitution-matiere": "Constitution et transformations de la matière",
    "mouvement-interactions": "Mouvement et interactions",
    "energie-conversions": "L’énergie : conversions et transferts",
    "ondes-signaux": "Ondes et signaux",
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


def first_existing(paths: list[Path]) -> Path:
    for p in paths:
        if p.exists():
            return p
    raise FileNotFoundError("Aucun fichier trouvé parmi :\n" + "\n".join(map(str, paths)))


def load_programme() -> dict[str, Any]:
    p = first_existing(PROGRAMME_PATH_CANDIDATES)
    data = read_json(p)
    if not isinstance(data, dict):
        raise RuntimeError(f"Programme officiel invalide : {p}")
    print(f"Programme officiel lu : {p}")
    return data


def load_exercises() -> list[dict[str, Any]]:
    for p in EXERCISES_PATH_CANDIDATES:
        data = read_json(p)
        if isinstance(data, list):
            print(f"Exercices lus : {p} ({len(data)})")
            return data
    print("Aucun exercice généré trouvé ; les cours seront générés sans exemples.")
    return []


def normalize_theme_list(programme: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    themes = programme.get("themes")
    if isinstance(themes, list):
        for t in themes:
            if isinstance(t, dict):
                tid = t.get("theme_id") or t.get("id")
                if tid:
                    out[str(tid)] = t

    elif isinstance(themes, dict):
        for tid, t in themes.items():
            if isinstance(t, dict):
                item = dict(t)
                item.setdefault("theme_id", tid)
                out[tid] = item

    for tid in THEME_ORDER:
        if tid in programme and isinstance(programme[tid], dict):
            item = dict(programme[tid])
            item.setdefault("theme_id", tid)
            out[tid] = item

    aliases = {
        "Constitution et transformations de la matière": "constitution-matiere",
        "Mouvement et interactions": "mouvement-interactions",
        "L’énergie : conversions et transferts": "energie-conversions",
        "Ondes et signaux": "ondes-signaux",
        "Mesure et incertitudes": "mesure-incertitudes",
    }
    for k, tid in aliases.items():
        if k in programme and isinstance(programme[k], dict):
            item = dict(programme[k])
            item.setdefault("theme_id", tid)
            item.setdefault("titre", k)
            out[tid] = item

    return out


def attach_experimental_caps(programme: dict[str, Any], theme: dict[str, Any], theme_id: str) -> dict[str, Any]:
    theme = dict(theme)
    exp = programme.get("capacites_experimentales")
    if isinstance(exp, dict):
        common = exp.get("capacites_experimentales_communes") or []
        par_theme = exp.get("par_theme") or {}
        theme_specific = []
        if isinstance(par_theme, dict):
            theme_specific = par_theme.get(theme_id) or []
        theme["capacites_experimentales_communes"] = common
        theme["capacites_experimentales_theme"] = theme_specific
    return theme


def block_ids(theme: dict[str, Any]) -> list[str]:
    ids = []
    for i, sp in enumerate(theme.get("sous_parties", []) or [], start=1):
        if isinstance(sp, dict):
            ids.append(str(sp.get("id") or f"{theme.get('theme_id', 'theme')}-bloc-{i:03d}"))
    return ids


def safe_examples(exercises: list[dict[str, Any]], theme_id: str, limit: int = 8) -> list[dict[str, Any]]:
    examples = []
    for ex in exercises:
        if ex.get("thematique_id") != theme_id:
            continue
        examples.append({
            "id": ex.get("id"),
            "titre": ex.get("titre"),
            "annee": ex.get("annee"),
            "session": ex.get("session"),
            "zone": ex.get("zone"),
            "notions": (ex.get("notions") or [])[:8],
            "mots_cles": (ex.get("mots_cles") or [])[:8],
        })
        if len(examples) >= limit:
            break
    return examples


def json_from_text(text: str) -> Any:
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)

    try:
        return json.loads(s)
    except Exception:
        pass

    starts = [x for x in [s.find("{"), s.find("[")] if x >= 0]
    if not starts:
        raise ValueError("Aucun début JSON trouvé dans la réponse Claude.")
    start = min(starts)
    opener = s[start]
    closer = "}" if opener == "{" else "]"
    end = s.rfind(closer)
    if end <= start:
        raise ValueError("Aucune fin JSON trouvée dans la réponse Claude.")
    return json.loads(s[start:end + 1])


def call_claude_json(client: anthropic.Anthropic, prompt: str, *, model: str, max_tokens: int, temperature: float, max_retries: int) -> Any:
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            chunks: list[str] = []
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=(
                    "Tu es un professeur français de physique-chimie de Terminale et un concepteur "
                    "de ressources de révision pour le baccalauréat. Tu produis uniquement du JSON valide."
                ),
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
            return json_from_text("".join(chunks))

        except Exception as exc:
            last_error = exc
            wait = 3 * attempt
            print(f"Erreur Claude tentative {attempt}/{max_retries}: {exc}. Pause {wait}s", file=sys.stderr)
            time.sleep(wait)

    raise RuntimeError(f"Échec génération cours : {last_error}")


def prompt_for_course(theme_id: str, official_theme: dict[str, Any], examples: list[dict[str, Any]]) -> str:
    title = THEME_LABELS.get(theme_id, official_theme.get("titre", theme_id))
    ids = block_ids(official_theme)

    return f"""
Tu dois produire une fiche de cours exhaustive pour la révision du baccalauréat français de spécialité physique-chimie Terminale.

SOURCE NORMATIVE :
Le cours doit être établi exclusivement à partir du programme officiel structuré fourni ci-dessous.
Les exemples d’exercices servent uniquement à adapter les conseils de méthode au bac. Ils ne doivent pas limiter le périmètre du cours.

THÈME :
- theme_id : {theme_id}
- titre : {title}

CONTRAINTES ABSOLUES :
- Réponds uniquement en JSON valide.
- Couvre tous les blocs du programme fournis dans "programme_officiel".
- N’ajoute pas de notions hors programme.
- Le cours doit être utile à un élève de Terminale : clair, structuré, mais rigoureux.
- Les formules doivent être en LaTeX simple.
- Ne produis pas directement de Mermaid fragile : produis une carte mentale structurée.
- "blocs_programme_couverts" doit contenir tous les identifiants suivants : {ids}

FORMAT JSON STRICT :
{{
  "theme_id": "{theme_id}",
  "titre": "{title}",
  "synthese": "Synthèse structurée en 250 à 450 mots.",
  "objectifs_bac": ["objectif exigible formulé pour l'élève"],
  "definitions": [
    {{
      "terme": "Terme",
      "definition": "Définition claire et conforme au programme",
      "bloc_programme": "id du bloc"
    }}
  ],
  "formules": [
    {{
      "nom": "Nom de la formule",
      "formule": "LaTeX simple, par exemple F = m a",
      "variables": "Définition des variables et unités",
      "conditions": "Conditions d'application",
      "bloc_programme": "id du bloc"
    }}
  ],
  "methodes": [
    {{
      "titre": "Méthode type bac",
      "etapes": ["étape 1", "étape 2"],
      "points_vigilance": ["vigilance 1"],
      "bloc_programme": "id du bloc"
    }}
  ],
  "capacites_experimentales": [
    {{
      "capacite": "capacité expérimentale",
      "ce_qu_il_faut_savoir_faire": "formulation élève",
      "bloc_programme": "id ou transversal"
    }}
  ],
  "capacites_numeriques_mathematiques": [
    {{
      "capacite": "capacité numérique ou mathématique",
      "mise_en_oeuvre": "ce qu'il faut savoir faire",
      "bloc_programme": "id du bloc"
    }}
  ],
  "carte_mentale": {{
    "titre": "{title}",
    "branches": [
      {{
        "nom": "Branche",
        "items": ["item 1", "item 2"]
      }}
    ]
  }},
  "conseils_bac": ["Conseil précis pour traiter les exercices de bac"],
  "exemples_exercices_associes": [
    {{
      "id": "id exercice",
      "titre": "titre",
      "usage": "ce que cet exercice permet de travailler"
    }}
  ],
  "blocs_programme_couverts": {json.dumps(ids, ensure_ascii=False)}
}}

PROGRAMME OFFICIEL STRUCTURÉ :
{json.dumps(official_theme, ensure_ascii=False, indent=2)}

EXEMPLES D’EXERCICES CLASSÉS DANS CE THÈME :
{json.dumps(examples, ensure_ascii=False, indent=2)}
""".strip()


def escape_mermaid_label(label: Any) -> str:
    s = str(label or "").replace('"', "'")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120]


def carte_to_mermaid(carte: dict[str, Any]) -> str:
    title = escape_mermaid_label(carte.get("titre", "Cours"))
    lines = ["graph TD", f'ROOT["{title}"]']
    branches = carte.get("branches") or []
    if not isinstance(branches, list):
        branches = []

    for i, b in enumerate(branches, start=1):
        if not isinstance(b, dict):
            continue
        bid = f"B{i}"
        lines.append(f'ROOT --> {bid}["{escape_mermaid_label(b.get("nom", f"Branche {i}"))}"]')
        items = b.get("items") or []
        if not isinstance(items, list):
            items = []
        for j, item in enumerate(items, start=1):
            iid = f"I{i}_{j}"
            lines.append(f'{bid} --> {iid}["{escape_mermaid_label(item)}"]')
    return "\n".join(lines)


def normalize_course(theme_id: str, obj: Any, official_theme: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        obj = {}

    obj.setdefault("theme_id", theme_id)
    obj.setdefault("titre", THEME_LABELS.get(theme_id, theme_id))
    obj.setdefault("synthese", "")
    obj.setdefault("objectifs_bac", [])
    obj.setdefault("definitions", [])
    obj.setdefault("formules", [])
    obj.setdefault("methodes", [])
    obj.setdefault("capacites_experimentales", [])
    obj.setdefault("capacites_numeriques_mathematiques", [])
    obj.setdefault("carte_mentale", {"titre": obj["titre"], "branches": []})
    obj.setdefault("conseils_bac", [])
    obj.setdefault("exemples_exercices_associes", [])
    obj.setdefault("blocs_programme_couverts", block_ids(official_theme))

    if isinstance(obj.get("carte_mentale"), dict):
        obj["carte_mentale_mermaid"] = carte_to_mermaid(obj["carte_mentale"])
    else:
        obj["carte_mentale"] = {"titre": obj["titre"], "branches": []}
        obj["carte_mentale_mermaid"] = carte_to_mermaid(obj["carte_mentale"])

    return obj


def coverage_report(courses: dict[str, Any], themes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for theme_id, theme in themes.items():
        expected = set(block_ids(theme))
        covered = set(courses.get(theme_id, {}).get("blocs_programme_couverts", []))
        for bid in sorted(expected):
            rows.append({
                "theme_id": theme_id,
                "bloc_programme": bid,
                "status": "couvert" if bid in covered else "manquant",
            })
    return rows


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère les fiches de cours depuis le programme officiel structuré, avec couverture exhaustive.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    args = parser.parse_args()

    if OUT_COURS.exists() and not args.force:
        print(f"{OUT_COURS} existe déjà. Utilise --force pour régénérer.")
        return

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY introuvable dans .env")

    programme = load_programme()
    themes = normalize_theme_list(programme)

    missing = [tid for tid in THEME_ORDER if tid not in themes]
    if missing:
        print("Thèmes disponibles :", sorted(themes))
        raise KeyError("Thèmes absents du programme officiel structuré : " + ", ".join(missing))

    themes = {tid: attach_experimental_caps(programme, themes[tid], tid) for tid in THEME_ORDER}

    exercises = load_exercises()
    client = anthropic.Anthropic(api_key=api_key)

    courses: dict[str, Any] = {}

    for theme_id in THEME_ORDER:
        print(f"\nGénération cours : {theme_id}")
        examples = safe_examples(exercises, theme_id, limit=8)
        obj = call_claude_json(
            client,
            prompt_for_course(theme_id, themes[theme_id], examples),
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            max_retries=args.max_retries,
        )
        courses[theme_id] = normalize_course(theme_id, obj, themes[theme_id])

        write_json(OUT_COURS, courses)
        write_json(OUT_COURS_GENERATED, courses)
        print(f"  -> OK ({len(courses[theme_id].get('blocs_programme_couverts', []))} blocs couverts déclarés)")

    rows = coverage_report(courses, themes)
    write_csv_rows(REPORTS / "programme_coverage.csv", rows)

    print("\nCours générés :")
    print(f"- {OUT_COURS}")
    print(f"- {OUT_COURS_GENERATED}")
    print(f"Rapport couverture : {REPORTS / 'programme_coverage.csv'}")

    missing_rows = [r for r in rows if r["status"] != "couvert"]
    if missing_rows:
        print(f"ATTENTION : blocs non couverts déclarés : {len(missing_rows)}")
    else:
        print("Couverture déclarée complète.")


if __name__ == "__main__":
    main()
