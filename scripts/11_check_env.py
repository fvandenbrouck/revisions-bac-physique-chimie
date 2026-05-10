#!/usr/bin/env python3
"""Vérifie que .env est lisible et que la configuration Claude est cohérente, sans afficher la clé."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    raise SystemExit("python-dotenv n'est pas installé. Lance : pip install -r requirements.txt")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def masked(value: str) -> str:
    if not value:
        return "ABSENTE"
    if len(value) <= 12:
        return "présente"
    return value[:10] + "..." + value[-4:]


def main() -> int:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    max_tokens = os.getenv("CLAUDE_MAX_TOKENS", "64000")
    temp = os.getenv("CLAUDE_TEMPERATURE", "0.1")

    print(f"Projet : {PROJECT_ROOT}")
    print(f".env : {'OK' if (PROJECT_ROOT / '.env').exists() else 'ABSENT'}")
    print(f"ANTHROPIC_API_KEY : {masked(key)}")
    print(f"CLAUDE_MODEL : {model}")
    print(f"CLAUDE_MAX_TOKENS : {max_tokens}")
    print(f"CLAUDE_TEMPERATURE : {temp}")

    if not key.startswith("sk-ant-"):
        print("ERREUR : ANTHROPIC_API_KEY est absente ou ne ressemble pas à une clé Anthropic.")
        return 2
    try:
        mt = int(max_tokens)
        if mt < 4096:
            print("ERREUR : CLAUDE_MAX_TOKENS est trop faible pour générer des corrigés complets.")
            return 2
    except ValueError:
        print("ERREUR : CLAUDE_MAX_TOKENS doit être un entier.")
        return 2

    print("Configuration locale cohérente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
