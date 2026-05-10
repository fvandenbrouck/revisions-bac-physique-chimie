from __future__ import annotations

from pathlib import Path
import os

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Charge automatiquement .env avant toute lecture de variable d'environnement.
# On teste le dossier projet, puis le dossier courant : cela couvre l'exécution depuis
# la racine du projet comme depuis un autre répertoire.
if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(Path.cwd() / ".env", override=False)

SITE_ROOT = Path(os.getenv("BAC_SITE_ROOT", PROJECT_ROOT / "site"))

PDF_DIR = SITE_ROOT / "pdf"
IMG_DIR = SITE_ROOT / "img"
DATA_DIR = SITE_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PAGES_DIR = RAW_DIR / "pages"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
GENERATED_DIR = DATA_DIR / "generated"
REPORTS_DIR = DATA_DIR / "rapports"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

MANIFEST_CSV = DATA_DIR / "manifest.csv"
MANIFEST_JSON = DATA_DIR / "manifest.json"
PROGRAMME_JSON = DATA_DIR / "programme.json"

PROGRAMME_DIR = SITE_ROOT / "programme"
PROGRAMME_PDF_PATH = Path(os.getenv("PROGRAMME_PDF_PATH", PROGRAMME_DIR / "Terminale PC.pdf"))
PROGRAMME_OFFICIEL_RAW_JSON = DATA_DIR / "programme_officiel_raw.json"
PROGRAMME_OFFICIEL_JSON = DATA_DIR / "programme_officiel.json"
PROGRAMME_COVERAGE_JSON = REPORTS_DIR / "programme_coverage.json"
EXERCISES_RAW_JSON = INTERMEDIATE_DIR / "exercises_raw.json"
EXERCISES_JSON = DATA_DIR / "exercices.json"
COURSES_JSON = DATA_DIR / "cours.json"
QUIZ_JSON = DATA_DIR / "quiz.json"
DATA_JSON = DATA_DIR / "data.json"

ALLOWED_THEMES = {
    "constitution-matiere": "Constitution et transformations de la matière",
    "mouvement-interactions": "Mouvement et interactions",
    "energie-conversions": "L’énergie : conversions et transferts",
    "ondes-signaux": "Ondes et signaux",
}

DIFFICULTY_MIN = 1
DIFFICULTY_MAX = 3

# Anthropic indique Sonnet 4.6 comme le Sonnet courant le plus équilibré/performant.
# Laisser surchargeable pour éviter de modifier les scripts lors d'une évolution du catalogue.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Plafond de sortie. Pour forcer un plafond très haut sur tous les appels Claude :
# CLAUDE_MAX_TOKENS=64000
# Les variables spécialisées ci-dessous peuvent surcharger ce plafond global.
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "64000"))
CLAUDE_MAX_TOKENS_PROGRAMME = int(os.getenv("CLAUDE_MAX_TOKENS_PROGRAMME", str(CLAUDE_MAX_TOKENS)))
CLAUDE_MAX_TOKENS_EXERCISE = int(os.getenv("CLAUDE_MAX_TOKENS_EXERCISE", str(CLAUDE_MAX_TOKENS)))
CLAUDE_MAX_TOKENS_COURSE = int(os.getenv("CLAUDE_MAX_TOKENS_COURSE", str(CLAUDE_MAX_TOKENS)))
CLAUDE_MAX_TOKENS_QUIZ = int(os.getenv("CLAUDE_MAX_TOKENS_QUIZ", str(CLAUDE_MAX_TOKENS)))
CLAUDE_TEMPERATURE = float(os.getenv("CLAUDE_TEMPERATURE", "0.1"))

DEFAULT_DPI = int(os.getenv("PDF_RENDER_DPI", "144"))

# Pour limiter les prompts trop volumineux. On conserve le texte complet dans le brut.
MAX_EXERCISE_TEXT_CHARS = int(os.getenv("MAX_EXERCISE_TEXT_CHARS", "42000"))

# Sécurité côté génération : on évite les chemins absolus dans les JSON du site.
SITE_RELATIVE_PREFIXES = ("img/", "pdf/", "data/")
