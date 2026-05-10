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

from dotenv import load_dotenv
import anthropic

from config import (
    DATA_DIR,
    EXERCISES_GENERATED_JSON,
    EXERCISES_RAW_JSON,
    GENERATED_DIR,
    PROJECT_ROOT,
)
from utils import read_json, write_json


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

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
# JSON utilities
# ---------------------------------------------------------------------------

def extract_json(text: str) -> Any:
    """
    Extract JSON from Claude output, even if a markdown fence appears.
    """
    s = (text or "").strip()

    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    starts = [i for i in [s.find("{"), s.find("[")] if i >= 0]
    if not starts:
        raise ValueError("Aucun début JSON trouvé dans la réponse Claude.")

    start = min(starts)
    opener = s[start]
    closer = "}" if opener == "{" else "]"
    end = s.rfind(closer)
    if end <= start:
        raise ValueError("Aucune fin JSON trouvée dans la réponse Claude.")

    return json.loads(s[start:end + 1])


def normalize_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_generated(ex: dict[str, Any], obj: Any) -> dict[str, Any]:
    """
    Force a stable shape for the generated exercise object.
    """
    if not isinstance(obj, dict):
        obj = {"corrige": str(obj)}

    out = dict(ex)

    out["thematique_id"] = obj.get("thematique_id") or obj.get("theme_id") or ""
    if out["thematique_id"] not in VALID_THEMES:
        # Keep value but mark invalid for validation if not recognized.
        pass

    out["notions"] = normalize_list(obj.get("notions"))
    out["mots_cles"] = normalize_list(obj.get("mots_cles") or obj.get("mots_clés"))
    out["difficulte"] = obj.get("difficulte", obj.get("difficulté", ""))
    out["aide"] = normalize_list(obj.get("aide"))
    out["competences"] = normalize_list(obj.get("competences") or obj.get("compétences"))
    out["points_vigilance"] = normalize_list(obj.get("points_vigilance"))

    corrige = obj.get("corrige") or obj.get("corrigé") or {}
    if isinstance(corrige, str):
        out["corrige"] = {
            "questions": [
                {
                    "numero": "global",
                    "reponse": corrige,
                    "points_attention": "",
                }
            ]
        }
    elif isinstance(corrige, dict):
        questions = corrige.get("questions")
        if isinstance(questions, list):
            out["corrige"] = corrige
        else:
            # Convert dict entries to list if possible.
            qlist = []
            for k, v in corrige.items():
                if isinstance(v, dict):
                    qlist.append({"numero": str(k), **v})
                else:
                    qlist.append({"numero": str(k), "reponse": str(v), "points_attention": ""})
            out["corrige"] = {"questions": qlist}
    elif isinstance(corrige, list):
        out["corrige"] = {"questions": corrige}
    else:
        out["corrige"] = {"questions": []}

    # Guarantee question keys.
    for q in out["corrige"].get("questions", []):
        if isinstance(q, dict):
            q.setdefault("numero", "")
            q.setdefault("reponse", "")
            q.setdefault("points_attention", "")

    out["generation"] = {
        "modele": DEFAULT_MODEL,
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

    # Limit input only if unexpectedly huge; one exercise should usually fit.
    texte = ex.get("texte_extrait") or ex.get("enonce") or ""
    if len(texte) > 60000:
        texte = texte[:60000] + "\n\n[TRONCATURE TECHNIQUE : exercice très long, vérifier les pages images.]"

    return f"""
Tu dois produire une fiche complète de révision pour un exercice de bac français de spécialité physique-chimie Terminale.

CONTRAINTES ABSOLUES :
- Réponds uniquement en JSON valide, sans Markdown.
- N’invente pas de donnée absente.
- Si une valeur doit être lue sur une figure ou un graphique, écris explicitement : "valeur à lire sur la figure".
- Le corrigé doit être complet, question par question.
- Les questions détectées dans l’énoncé doivent toutes être présentes dans corrige.questions.
- Les formules doivent être écrites en LaTeX simple quand c’est utile.
- Le niveau attendu est Terminale spécialité physique-chimie.
- Ne produis pas de carte mentale ici.
- Classe l’exercice dans un seul des quatre thèmes autorisés :
  1. constitution-matiere
  2. mouvement-interactions
  3. energie-conversions
  4. ondes-signaux

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
        "reponse": "Réponse complète avec démarche et unités.",
        "points_attention": "Erreur fréquente ou vigilance."
      }}
    ]
  }},
  "points_vigilance": [
    "point de vigilance"
  ]
}}

MÉTADONNÉES DE L’EXERCICE :
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
# Optional image support
# ---------------------------------------------------------------------------

def image_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    suffix = path.suffix.lower()
    if suffix == ".png":
        media_type = "image/png"
    elif suffix in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    elif suffix == ".webp":
        media_type = "image/webp"
    else:
        return None

    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": data,
        },
    }


def build_messages_content(ex: dict[str, Any], include_images: bool) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {"type": "text", "text": build_prompt(ex)}
    ]

    if include_images:
        # Add up to 4 page images to keep payload reasonable.
        for rel in (ex.get("page_images") or [])[:4]:
            p = PROJECT_ROOT / "site" / rel
            payload = image_payload(p)
            if payload:
                content.append(payload)

    return content


# ---------------------------------------------------------------------------
# Anthropic streaming call
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
                        "content": build_messages_content(ex, include_images),
                    }
                ],
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)

            raw = "".join(chunks)
            parsed = extract_json(raw)
            return normalize_generated(ex, parsed)

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

def load_existing_generated() -> list[dict[str, Any]]:
    data = read_json(EXERCISES_GENERATED_JSON)
    if isinstance(data, list):
        return data
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère aides, classifications et corrigés avec Claude, en streaming.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true", help="Régénère même si l'exercice existe déjà.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--vision", action="store_true", help="Envoie aussi les images de pages à Claude. Plus coûteux.")
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY introuvable. Vérifie le fichier .env.")

    raw_exercises = read_json(EXERCISES_RAW_JSON)
    if not isinstance(raw_exercises, list) or not raw_exercises:
        raise RuntimeError(f"Aucun exercice brut trouvé dans {EXERCISES_RAW_JSON}")

    existing = load_existing_generated()
    existing_by_id = {ex.get("id"): ex for ex in existing if ex.get("id")}

    to_process = []
    for ex in raw_exercises:
        ex_id = ex.get("id")
        if not args.force and ex_id in existing_by_id:
            continue
        to_process.append(ex)

    if args.limit:
        to_process = to_process[: args.limit]

    print(f"Modèle Claude : {args.model}")
    print(f"Max tokens : {args.max_tokens}")
    print(f"Vision images : {'oui' if args.vision else 'non'}")
    print(f"Exercices à générer : {len(to_process)} / {len(raw_exercises)}")

    if not to_process:
        print("Rien à générer.")
        return

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic(api_key=api_key)

    generated_by_id = dict(existing_by_id)
    errors: list[dict[str, Any]] = []

    for idx, ex in enumerate(to_process, start=1):
        ex_id = ex.get("id", f"ex-{idx}")
        title = ex.get("titre", "")
        print(f"[{idx}/{len(to_process)}] {ex_id} — {title}")

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

            # Save after each exercise to make the script restartable.
            ordered = [generated_by_id[e.get("id")] for e in raw_exercises if e.get("id") in generated_by_id]
            write_json(EXERCISES_GENERATED_JSON, ordered)

            # Also save individual file.
            one_path = GENERATED_DIR / "exercices" / f"{ex_id}.json"
            one_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(one_path, generated)

            print("  -> OK")

        except KeyboardInterrupt:
            print("\nInterruption utilisateur. Les exercices déjà générés ont été sauvegardés.")
            raise
        except Exception as exc:
            print(f"  -> ERREUR : {exc}")
            errors.append({"id": ex_id, "titre": title, "erreur": str(exc)})

    if errors:
        err_path = DATA_DIR / "rapports" / "generation_exercises_errors.json"
        err_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(err_path, errors)
        print(f"\nErreurs enregistrées : {err_path}")

    final_count = len(generated_by_id)
    print(f"\nGénération terminée. Exercices générés disponibles : {final_count}")
    print(f"Fichier global : {EXERCISES_GENERATED_JSON}")


if __name__ == "__main__":
    main()
