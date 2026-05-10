#!/usr/bin/env python3
"""Crée/vérifie l'architecture locale du projet bac physique-chimie."""
from __future__ import annotations

from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRS = [
    "site",
    "site/pdf",
    "site/programme",
    "site/img",
    "site/data",
    "site/data/raw",
    "site/data/raw/pages",
    "site/data/intermediate",
    "site/data/generated",
    "site/data/rapports",
]


def main() -> int:
    print(f"Projet détecté : {PROJECT_ROOT}")
    for rel in REQUIRED_DIRS:
        path = PROJECT_ROOT / rel
        path.mkdir(parents=True, exist_ok=True)
        print(f"OK  {rel}/")

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        print("OK  .env présent à la racine du projet")
    else:
        print("ATTENTION  .env absent")
        print("Crée-le ainsi, depuis la racine du projet :")
        print("cat > .env <<'EOF'")
        print("ANTHROPIC_API_KEY=VOTRE_CLE_ANTHROPIC_ICI")
        print("CLAUDE_MODEL=claude-sonnet-4-6")
        print("CLAUDE_MAX_TOKENS=64000")
        print("CLAUDE_TEMPERATURE=0.1")
        print("EOF")
        print("chmod 600 .env")

    programme = PROJECT_ROOT / "site" / "programme" / "Terminale PC.pdf"
    if programme.exists():
        print("OK  programme officiel trouvé : site/programme/Terminale PC.pdf")
    else:
        print("INFO programme officiel non trouvé : copie Terminale PC.pdf dans site/programme/")

    pdfs = list((PROJECT_ROOT / "site" / "pdf").glob("*.pdf"))
    print(f"PDF sujets détectés dans site/pdf/ : {len(pdfs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
