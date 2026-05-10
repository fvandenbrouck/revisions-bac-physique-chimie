#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
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


# ---------------------------------------------------------------------------
# Script autonome : ne dépend pas de config.py
# ---------------------------------------------------------------------------

def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p.parent, *p.parents]:
        if (parent / "site").exists() and (parent / "scripts").exists():
            return parent
    return Path.cwd()


PROJECT_ROOT = find_project_root()
SITE_DIR = PROJECT_ROOT / "site"
DATA_DIR = SITE_DIR / "data"
RAW_EXERCISES_PATH = DATA_DIR / "intermediate" / "exercises_raw.json"

# On écrit plusieurs sorties pour compatibilité avec les autres scripts.
GENERATED_DIR = DATA_DIR / "generated"
GENERATED_EXERCISES_PATH = GENERATED_DIR / "exercices.json"
SITE_EXERCISES_PATH = DATA_DIR / "exercices.json"
REPORTS_DIR = DATA_DIR / "rapports"

if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = int(
    os.getenv(
        "CLAUDE_MAX_TOKENS_EXERCISE",
        os.getenv("CLAUDE_MAX_TOKENS", "64000"),
    )
)
DEFAULT_TEMPERATURE = float(os.getenv("CLAUDE_TEMPERATURE", "0.1"))

VALID_THEMES = {
    "constitution-matiere",
    "mouvement-interactions",
    "energie-conversions",
    "ondes-signaux",
}


# ---------------------------------------------------------------------------
# Fichiers JSON
# ---------------------------------------------------------------------------

def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_existing_generated() -> list[dict[str, Any]]:
    # priorité à site/data/generated/exercices.json, fallback site/data/exercices.json
    for p in [GENERATED_EXERCISES_PATH, SITE_EXERCISES_PATH]:
        data = read_json(p)
        if isinstance(data, list):
            return data
    return []


def save_generated(raw_exercises: list[dict[str, Any]], generated_by_id: dict[str, dict[str, Any]]) -> None:
    ordered = [generated_by_id[e.get("id")] for e in raw_exercises if e.get("id") in generated_by_id]
    write_json(GENERATED_EXERCISES_PATH, ordered)
    write_json(SITE_EXERCISES_PATH, ordered)


# ---------------------------------------------------------------------------
# JSON Claude
# ---------------------------------------------------------------------------

def extract_json(text: str) -> Any:
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)

    try:
        return json.loads(s)
    except json.JSONDecodeError:
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

    candidate = s[start:end + 1]
    return json.loads(candidate)


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_generated(ex: dict[str, Any], obj: Any, model: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        obj = {"corrige": str(obj)}

    out = dict(ex)

    out["thematique_id"] = obj.get("thematique_id") or obj.get("theme_id") or ""
    out["notions"] = as_list(obj.get("notions"))
    out["mots_cles"] = as_list(obj.get("mots_cles") or obj.get("mots_clés"))
    out["difficulte"] = obj.get("difficulte", obj.get("difficulté", ""))
    out["competences"] = as_list(obj.get("competences") or obj.get("compétences"))
    out["aide"] = as_list(obj.get("aide"))
    out["points_vigilance"] = as_list(obj.get("points_vigilance"))

    corrige = obj.get("corrige") or obj.get("corrigé") or {}
    questions: list[dict[str, Any]] = []

    if isinstance(corrige, str):
        questions = [{"numero": "global", "reponse": corrige, "points_attention": ""}]
    elif isinstance(corrige, dict):
        q = corrige.get("questions")
        if isinstance(q, list):
            questions = q
        else:
            for k, v in corrige.items():
                if isinstance(v, dict):
                    item = {"numero": str(k)}
                    item.update(v)
                    questions.append(item)
                else:
                    questions.append({"numero": str(k), "reponse": str(v), "points_attention": ""})
    elif isinstance(corrige, list):
        questions = corrige

    normalized_questions = []
    for item in questions:
        if isinstance(item, dict):
            normalized_questions.append(
                {
                    "numero": str(item.get("numero", "")),
                    "reponse": str(item.get("reponse", item.get("réponse", ""))),
                    "points_attention": str(item.get("points_attention", item.get("vigilance", ""))),
                }
            )
        else:
            normalized_questions.append({"numero": "", "reponse": str(item), "points_attention": ""})

    out["corrige"] = {"questions": normalized_questions}
    out["generation"] = {
        "modele": model,
        "source": "Claude API",
        "statut": "genere",
    }

    return out


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_prompt(ex: dict[str, Any]) -> str:
    questions = ex.get("questions_detectees") or []
    if isinstance(questions, str):
        questions = [questions]
    questions_text = ", ".join(str(q) for q in questions) if questions else "non détectées automatiquement"

    texte = ex.get("texte_extrait") or ex.get("enonce") or ""
    # Sécurité : les pages images restent disponibles dans le site ; éviter de noyer Claude.
    if len(texte) > 65000:
        texte = texte[:65000] + "\n\n[TRONCATURE TECHNIQUE : exercice très long ; certaines valeurs peuvent devoir être lues sur les pages images.]"

    return f"""
Tu dois produire une fiche complète de révision pour un exercice de baccalauréat français de spécialité physique-chimie, niveau Terminale.

CONTRAINTES ABSOLUES :
- Réponds uniquement en JSON valide, sans Markdown.
- N’invente pas de valeur absente de l’énoncé.
- Si une valeur doit être lue sur une figure, un graphe ou un tableau peu lisible, écris explicitement : "valeur à lire sur la figure".
- Le corrigé doit être complet, question par question.
- Les questions détectées dans l’énoncé doivent toutes apparaître dans corrige.questions.
- Si les questions sont notées 1., 2., 3. et non Q1, Q2, conserve cette numérotation.
- Les calculs doivent mentionner les unités.
- Les formules utiles doivent être écrites en LaTeX simple.
- Ne produis pas de carte mentale.
- Classe l’exercice dans un seul des quatre thèmes autorisés :
  constitution-matiere
  mouvement-interactions
  energie-conversions
  ondes-signaux

FORMAT JSON STRICT :
{{
  "thematique_id": "constitution-matiere | mouvement-interactions | energie-conversions | ondes-signaux",
  "notions": ["notion 1", "notion 2"],
  "mots_cles": ["mot clé 1", "mot clé 2"],
  "difficulte": 1,
  "competences": ["S’approprier", "Analyser/Raisonner", "Réaliser", "Valider", "Communiquer"],
  "aide": [
    "Q1 — Méthode : ...",
    "Q2 — Méthode : ..."
  ],
  "corrige": {{
    "questions": [
      {{
        "numero": "Q1",
        "reponse": "Réponse complète avec démarche, calculs utiles et unités.",
        "points_attention": "Erreur fréquente ou vigilance."
      }}
    ]
  }},
  "points_vigilance": [
    "point de vigilance"
  ]
}}

MÉTADONNÉES :
- id : {ex.get("id", "")}
- année : {ex.get("annee", "")}
- session : {ex.get("session", "")}
- zone : {ex.get("zone", "")}
- titre : {ex.get("titre", "")}
- type : {ex.get("type", "")}
- points : {ex.get("points", "")}
- pages : {ex.get("pages", "")}
- questions détectées : {questions_text}

ÉNONCÉ EXTRAIT :
\"\"\"
{texte}
\"\"\"
""".strip()


# ---------------------------------------------------------------------------
# Images optionnelles
# ---------------------------------------------------------------------------

def image_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    suffix = path.suffix.lower()
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix)
    if not media:
        return None

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media,
            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        },
    }


def build_content(ex: dict[str, Any], include_images: bool) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": build_prompt(ex)}]

    if include_images:
        # Limite volontaire : envoyer toutes les pages des gros exercices serait lent et coûteux.
        for rel in (ex.get("page_images") or [])[:4]:
            p = SITE_DIR / rel
            payload = image_payload(p)
            if payload:
                content.append(payload)

    return content


# ---------------------------------------------------------------------------
# Claude streaming
# ---------------------------------------------------------------------------

def call_claude_streaming(
    client: anthropic.Anthropic,
    ex: dict[str, Any],
    *,
    include_images: bool,
    model: str,
    max_tokens: int,
    temperature: float,
    max_retries: int,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            chunks: list[str] = []

            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=(
                    "Tu es un professeur français de physique-chimie de Terminale, "
                    "expert des sujets du baccalauréat. Tu produis uniquement du JSON valide."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": build_content(ex, include_images),
                    }
                ],
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)

            parsed = extract_json("".join(chunks))
            return normalize_generated(ex, parsed, model)

        except Exception as exc:
            last_error = exc
            sleep = 2 * attempt
            print(
                f"Erreur Claude pour {ex.get('id')} tentative {attempt}/{max_retries}: {exc}. Pause {sleep}s",
                file=sys.stderr,
            )
            time.sleep(sleep)

    raise RuntimeError(f"Échec après {max_retries} tentatives: {last_error}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Génère aides, classifications et corrigés avec Claude en streaming.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true", help="Régénère même si l'exercice existe déjà.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--vision", action="store_true", help="Ajoute les images de pages. Plus lent et coûteux.")
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY introuvable. Vérifie .env à la racine du projet.")

    raw = read_json(RAW_EXERCISES_PATH)
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"Aucun exercice brut trouvé : {RAW_EXERCISES_PATH}")

    existing = load_existing_generated()
    generated_by_id = {ex.get("id"): ex for ex in existing if isinstance(ex, dict) and ex.get("id")}

    to_process = []
    for ex in raw:
        ex_id = ex.get("id")
        if args.force or ex_id not in generated_by_id:
            to_process.append(ex)

    if args.limit:
        to_process = to_process[: args.limit]

    print(f"Projet : {PROJECT_ROOT}")
    print(f"Modèle Claude : {args.model}")
    print(f"Max tokens : {args.max_tokens}")
    print(f"Vision images : {'oui' if args.vision else 'non'}")
    print(f"Exercices à générer : {len(to_process)} / {len(raw)}")

    if not to_process:
        print("Rien à générer.")
        return

    client = anthropic.Anthropic(api_key=api_key)
    errors: list[dict[str, Any]] = []

    for idx, ex in enumerate(to_process, start=1):
        ex_id = ex.get("id", f"ex-{idx}")
        print(f"[{idx}/{len(to_process)}] {ex_id} — {ex.get('titre', '')}")

        try:
            generated = call_claude_streaming(
                client,
                ex,
                include_images=args.vision,
                model=args.model,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                max_retries=args.max_retries,
            )

            generated_by_id[ex_id] = generated
            save_generated(raw, generated_by_id)

            one_path = GENERATED_DIR / "exercises" / f"{ex_id}.json"
            write_json(one_path, generated)

            print("  -> OK")

        except KeyboardInterrupt:
            print("\nInterruption utilisateur. Les résultats déjà obtenus sont sauvegardés.")
            raise
        except Exception as exc:
            print(f"  -> ERREUR : {exc}")
            errors.append({"id": ex_id, "titre": ex.get("titre", ""), "erreur": str(exc)})

    if errors:
        write_json(REPORTS_DIR / "generation_exercises_errors.json", errors)
        print(f"\nErreurs enregistrées : {REPORTS_DIR / 'generation_exercises_errors.json'}")

    print(f"\nGénération terminée.")
    print(f"Fichier principal : {GENERATED_EXERCISES_PATH}")
    print(f"Copie site       : {SITE_EXERCISES_PATH}")
    print(f"Exercices générés disponibles : {len(generated_by_id)}")


if __name__ == "__main__":
    main()
