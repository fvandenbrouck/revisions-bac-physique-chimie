#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from config import (
    ALLOWED_THEMES,
    CLAUDE_MAX_TOKENS_QUIZ,
    CLAUDE_MODEL,
    CLAUDE_TEMPERATURE,
    COURSES_JSON,
    QUIZ_JSON,
)
from utils import parse_json_object, read_json, write_json

SYSTEM_PROMPT = """Tu es un enseignant de physique-chimie de terminale.
Tu crées des QCM de révision brefs, fiables, sans ambiguïté.
Pour chaque thème, produire exactement 10 questions.

Répartition attendue :
- 2 questions de connaissance notionnelle ;
- 3 questions sur les relations fondamentales ;
- 2 questions de raisonnement qualitatif ;
- 2 questions d’exploitation numérique simple ;
- 1 question ciblant une erreur fréquente.

Parmi les questions sur les relations fondamentales, les distracteurs doivent correspondre à des erreurs classiques :
- inversion numérateur/dénominateur ;
- puissance fausse ;
- oubli d’un carré ;
- confusion entre grandeur et dérivée ;
- confusion entre constante de temps, demi-vie et constante cinétique ;
- relation non homogène.
Exemples de relations à tester lorsque le thème s’y prête :
- troisième loi de Kepler : a³/T² = constante, et non a²/T³ ;
- accélération centripète : a = v²/R, et non v/R ;
- condensateur : i = C du/dt, et non u = C di/dt ;
- demi-vie pour une cinétique d’ordre 1 : t1/2 = ln(2)/k ;
- effet Joule : P = R I² ;
- onde progressive périodique : v = λ f ;
- fréquence et période : f = 1/T ;
- énergie cinétique : Ec = 1/2 m v² ;
- Beer-Lambert : A = ε ℓ C ;
- pH = -log[H3O+].
Tu retournes uniquement du JSON valide.
"""


def build_prompt(theme_id: str, course: dict[str, Any], n: int) -> str:
    return f"""
À partir de cette fiche de cours, produis {n} questions de quiz pour réviser la thématique {theme_id}.

Format JSON strict attendu :
[
  {{
    "question": "...",
    "options": ["réponse A", "réponse B", "réponse C", "réponse D"],
    "correct": 0,
    "explanation": "explication courte"
  }}
]

Contraintes :
- exactly 4 options per question ;
- correct est un entier de 0 à 3 ;
- éviter les pièges absurdes ;
- une seule réponse correcte ;
- pas de Markdown.

Fiche de cours :
{course}
""".strip()


def call(
    client: Anthropic,
    theme_id: str,
    course: dict[str, Any],
    n: int,
    model: str,
    max_retries: int,
) -> list[dict[str, Any]]:
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            chunks: list[str] = []

            with client.messages.stream(
                model=model,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(theme_id, course, n)}],
                max_tokens=CLAUDE_MAX_TOKENS_QUIZ,
                temperature=CLAUDE_TEMPERATURE,
            ) as stream:
                for text_delta in stream.text_stream:
                    chunks.append(text_delta)

            text = "".join(chunks)

            obj = parse_json_object(text)
            if not isinstance(obj, list):
                raise ValueError("Réponse non-liste.")

            clean = []
            for q in obj:
                if not isinstance(q, dict):
                    continue

                options = q.get("options") or []
                if len(options) != 4:
                    continue

                correct = int(q.get("correct"))
                if correct < 0 or correct > 3:
                    continue

                clean.append(
                    {
                        "question": str(q.get("question", "")),
                        "options": [str(o) for o in options],
                        "correct": correct,
                        "explanation": str(q.get("explanation", "")),
                    }
                )

            if not clean:
                raise ValueError("Aucune question valide.")

            return clean

        except Exception as exc:  # noqa: BLE001
            last_error = exc
            sleep = min(20, 2 * attempt)
            print(
                f"Erreur quiz {theme_id} tentative {attempt}/{max_retries}: {exc}. Pause {sleep}s",
                file=sys.stderr,
            )
            time.sleep(sleep)

    raise RuntimeError(f"Échec génération quiz {theme_id}: {last_error}")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Génère un quiz local par thématique à partir des fiches de cours."
    )
    parser.add_argument("--model", default=CLAUDE_MODEL)
    parser.add_argument("--questions-per-theme", type=int, default=10)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY absent.", file=sys.stderr)
        sys.exit(1)

    courses = read_json(COURSES_JSON, default={}) or {}
    if not courses:
        print("cours.json absent ou vide. Lancer 05_generate_courses.py d'abord.", file=sys.stderr)
        sys.exit(1)

    client = Anthropic()
    quiz = {}

    for theme_id in ALLOWED_THEMES:
        course = courses.get(theme_id)

        if not course:
            quiz[theme_id] = []
            continue

        quiz[theme_id] = call(
            client,
            theme_id,
            course,
            args.questions_per_theme,
            args.model,
            args.max_retries,
        )
        print(f"Quiz généré : {theme_id} ({len(quiz[theme_id])} questions)")

    write_json(QUIZ_JSON, quiz)
    print(f"Quiz écrit : {QUIZ_JSON}")


if __name__ == "__main__":
    main()
