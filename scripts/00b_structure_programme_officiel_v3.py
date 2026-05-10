#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    import anthropic
except Exception:
    print("ERREUR : module anthropic absent. Lance : python -m pip install anthropic python-dotenv")
    raise


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------

def find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p.parent, *p.parents]:
        if (parent / "site").exists() and (parent / "scripts").exists():
            return parent
    return Path.cwd()


ROOT = find_project_root()
SITE = ROOT / "site"
DATA = SITE / "data"
PROGRAMME_PDF = SITE / "programme" / "Terminale PC.pdf"

OUT_MAIN = DATA / "programme_officiel.json"
OUT_GENERATED = DATA / "generated" / "programme_officiel.json"
OUT_SECTIONS_DEBUG = DATA / "programme_officiel_sections_debug.json"

if load_dotenv:
    load_dotenv(ROOT / ".env")

DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS_PROGRAMME", os.getenv("CLAUDE_MAX_TOKENS", "64000")))
DEFAULT_TEMPERATURE = float(os.getenv("CLAUDE_TEMPERATURE", "0.1"))


# ---------------------------------------------------------------------------
# Définition attendue des thèmes
# ---------------------------------------------------------------------------

THEMES = {
    "mesure-incertitudes": {
        "titre": "Mesure et incertitudes",
        "pages_1based": [6, 7, 8],
        "start": r"Mesure\s+et\s+incertitudes",
        "end": r"Constitution\s+et\s+transformations\s+de\s+la\s+mati[èe]re",
        "outline": [
            "Variabilité de la mesure d’une grandeur physique",
            "Incertitude-type",
            "Incertitudes-types composées",
            "Écriture du résultat et comparaison à une valeur de référence",
        ],
        "minimum_blocks": 4,
    },
    "constitution-matiere": {
        "titre": "Constitution et transformations de la matière",
        "pages_1based": list(range(8, 20)),
        "start": r"Constitution\s+et\s+transformations\s+de\s+la\s+mati[èe]re",
        "end": r"Mouvement\s+et\s+interactions",
        "outline": [
            "Modéliser des transformations acide-base par des transferts d’ion hydrogène H+",
            "Analyser un système chimique par des méthodes physiques",
            "Analyser un système par des méthodes chimiques",
            "Suivre et modéliser l’évolution temporelle d’un système siège d’une transformation chimique",
            "Modélisation microscopique : mécanisme réactionnel",
            "Transformation nucléaire : stabilité, radioactivités, équations",
            "Loi de décroissance radioactive et temps de demi-vie",
            "Applications de la radioactivité",
            "Équilibre chimique, quotient de réaction, constante d’équilibre",
            "Piles et oxydoréduction",
            "Force des acides et des bases, KA, Ke, pH",
            "Diagrammes de prédominance/distribution et solution tampon",
            "Électrolyse et passage forcé d’un courant",
            "Structure et propriétés en synthèse organique",
            "Optimisation, stratégie multi-étapes, protection/déprotection, synthèses écoresponsables",
        ],
        "minimum_blocks": 12,
    },
    "mouvement-interactions": {
        "titre": "Mouvement et interactions",
        "pages_1based": list(range(19, 24)),
        "start": r"Mouvement\s+et\s+interactions",
        "end": r"L[’']?énergie\s*:\s*conversions\s+et\s+transferts|L.?énergie\s*:\s*conversions\s+et\s+transferts",
        "outline": [
            "Décrire un mouvement : vecteurs position, vitesse, accélération",
            "Repère de Frenet et mouvements rectiligne/circulaire",
            "Relier les actions appliquées à un système à son mouvement : deuxième loi de Newton",
            "Mouvement dans un champ uniforme : pesanteur et champ électrique",
            "Aspects énergétiques du mouvement dans un champ uniforme",
            "Mouvement dans un champ de gravitation : satellites, planètes, Kepler",
            "Modéliser l’écoulement d’un fluide : poussée d’Archimède, débit, Bernoulli, Venturi",
        ],
        "minimum_blocks": 6,
    },
    "energie-conversions": {
        "titre": "L’énergie : conversions et transferts",
        "pages_1based": list(range(23, 26)),
        "start": r"L[’']?énergie\s*:\s*conversions\s+et\s+transferts|L.?énergie\s*:\s*conversions\s+et\s+transferts",
        "end": r"Ondes\s+et\s+signaux",
        "outline": [
            "Modèle du gaz parfait : pression, température thermodynamique, masse volumique",
            "Équation d’état du gaz parfait et limites du modèle",
            "Énergie interne et contributions microscopiques",
            "Premier principe de la thermodynamique, transfert thermique, travail",
            "Capacité thermique d’un système incompressible et bilan énergétique",
            "Modes de transfert thermique, flux thermique, résistance thermique",
            "Bilan thermique Terre-atmosphère, albédo, effet de serre",
            "Loi phénoménologique de Newton et évolution temporelle de la température",
        ],
        "minimum_blocks": 7,
    },
    "ondes-signaux": {
        "titre": "Ondes et signaux",
        "pages_1based": list(range(25, 31)),
        "start": r"Ondes\s+et\s+signaux",
        "end": r"Capacit[ée]s\s+exp[ée]rimentales",
        "outline": [
            "Intensité sonore, niveau d’intensité sonore, atténuation",
            "Diffraction d’une onde",
            "Interférences de deux ondes mécaniques",
            "Interférences de deux ondes lumineuses, différence de chemin optique, interfrange",
            "Effet Doppler et décalage Doppler",
            "Lunette astronomique afocale et grossissement",
            "Photon, effet photoélectrique, travail d’extraction",
            "Absorption/émission de photons et rendement photovoltaïque",
            "Dynamique d’un système électrique : courant variable, condensateur, circuit RC, capteurs capacitifs",
        ],
        "minimum_blocks": 8,
    },
}

EXPERIMENTAL_CAPS = {
    "pages_1based": [31, 32, 33],
    "start": r"Capacit[ée]s\s+exp[ée]rimentales",
    "end": None,
}


# ---------------------------------------------------------------------------
# Extraction PDF
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = text.replace("￾", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_pdf_pages(pdf: Path) -> dict[int, str]:
    if fitz is None:
        raise RuntimeError("PyMuPDF absent. Lance : python -m pip install pymupdf")
    if not pdf.exists():
        raise FileNotFoundError(f"PDF programme introuvable : {pdf}")

    doc = fitz.open(pdf)
    pages: dict[int, str] = {}
    for i, page in enumerate(doc, start=1):
        pages[i] = page.get_text("text") or ""
    return pages


def page_text(pages: dict[int, str], page_numbers: list[int]) -> str:
    return clean_text("\n\n".join(pages.get(n, "") for n in page_numbers))


def slice_between(text: str, start_pat: str | None, end_pat: str | None) -> str:
    flags = re.IGNORECASE | re.MULTILINE
    start_idx = 0
    if start_pat:
        m = re.search(start_pat, text, flags)
        if m:
            start_idx = m.start()

    end_idx = len(text)
    if end_pat:
        m = re.search(end_pat, text[start_idx + 1 :], flags)
        if m:
            end_idx = start_idx + 1 + m.start()

    return clean_text(text[start_idx:end_idx])


def build_sections_from_pdf() -> dict[str, str]:
    pages = read_pdf_pages(PROGRAMME_PDF)

    sections: dict[str, str] = {}
    for tid, spec in THEMES.items():
        txt = page_text(pages, spec["pages_1based"])
        sections[tid] = slice_between(txt, spec["start"], spec["end"])

    exp_txt = page_text(pages, EXPERIMENTAL_CAPS["pages_1based"])
    sections["capacites-experimentales"] = slice_between(exp_txt, EXPERIMENTAL_CAPS["start"], EXPERIMENTAL_CAPS["end"])

    # Debug pour contrôle humain
    debug = {
        tid: {
            "titre": THEMES.get(tid, {}).get("titre", tid),
            "caracteres": len(txt),
            "aperçu": txt[:800],
        }
        for tid, txt in sections.items()
    }
    write_json(OUT_SECTIONS_DEBUG, debug)
    return sections


# ---------------------------------------------------------------------------
# Claude JSON
# ---------------------------------------------------------------------------

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
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            chunks: list[str] = []
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=(
                    "Tu es un expert du programme officiel français de physique-chimie de terminale générale. "
                    "Tu structures fidèlement le texte officiel et tu réponds uniquement en JSON valide."
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
    raise RuntimeError(f"Échec structuration : {last_error}")


def prompt_theme(theme_id: str, text: str) -> str:
    spec = THEMES[theme_id]
    title = spec["titre"]
    outline = spec["outline"]
    min_blocks = spec["minimum_blocks"]

    return f"""
Tu dois structurer de manière exhaustive l'extrait officiel ci-dessous du programme français de Terminale spécialité Physique-Chimie.

THÈME :
- theme_id : {theme_id}
- titre : {title}

CONTRAINTES ABSOLUES :
- Tu ne dois utiliser que l'extrait officiel fourni.
- Tu ne dois pas importer de notions d'un autre thème.
- Tu dois couvrir toutes les lignes "Notions et contenus" et toutes les "Capacités exigibles".
- Tu dois produire au moins {min_blocks} blocs, sauf si l'extrait officiel en contient objectivement moins.
- Les blocs attendus doivent correspondre à cette structure indicative :
{json.dumps(outline, ensure_ascii=False, indent=2)}
- Les identifiants doivent être stables : {theme_id}-bloc-001, {theme_id}-bloc-002, etc.
- Réponse uniquement en JSON valide, sans Markdown.

FORMAT JSON STRICT :
{{
  "theme_id": "{theme_id}",
  "titre": "{title}",
  "resume_officiel": "Résumé neutre de 80 à 140 mots.",
  "sous_parties": [
    {{
      "id": "{theme_id}-bloc-001",
      "titre": "Titre du bloc",
      "notions": ["notion ou contenu officiel"],
      "capacites_exigibles": ["capacité exigible officielle"],
      "activites_experimentales": ["activité expérimentale support si mentionnée"],
      "capacites_numeriques": ["capacité numérique si mentionnée"],
      "capacites_mathematiques": ["capacité mathématique si mentionnée"],
      "mots_cles": ["mot-clé"]
    }}
  ],
  "couverture": {{
    "notions_total": 0,
    "capacites_total": 0,
    "remarques": []
  }}
}}

EXTRAIT OFFICIEL :
\"\"\"
{text}
\"\"\"
""".strip()


def prompt_experimental(text: str) -> str:
    return f"""
Tu dois structurer la section "Capacités expérimentales" du programme officiel de Terminale spécialité Physique-Chimie.

CONTRAINTES :
- Réponse uniquement en JSON valide.
- Reprendre toutes les capacités listées.
- Classer par thème officiel.
- Ne rien inventer.

FORMAT JSON STRICT :
{{
  "capacites_experimentales_communes": [],
  "par_theme": {{
    "constitution-matiere": [],
    "mouvement-interactions": [],
    "energie-conversions": [],
    "ondes-signaux": []
  }}
}}

EXTRAIT OFFICIEL :
\"\"\"
{text}
\"\"\"
""".strip()


def ensure_theme_shape(theme_id: str, obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        obj = {}

    obj.setdefault("theme_id", theme_id)
    obj.setdefault("titre", THEMES[theme_id]["titre"])
    obj.setdefault("resume_officiel", "")
    obj.setdefault("sous_parties", [])
    obj.setdefault("couverture", {})

    if not isinstance(obj["sous_parties"], list):
        obj["sous_parties"] = []

    for i, sp in enumerate(obj["sous_parties"], start=1):
        if not isinstance(sp, dict):
            sp = {"titre": str(sp)}
            obj["sous_parties"][i - 1] = sp

        sp.setdefault("id", f"{theme_id}-bloc-{i:03d}")
        sp.setdefault("titre", f"Bloc {i}")
        for key in [
            "notions",
            "capacites_exigibles",
            "activites_experimentales",
            "capacites_numeriques",
            "capacites_mathematiques",
            "mots_cles",
        ]:
            if not isinstance(sp.get(key), list):
                sp[key] = [] if sp.get(key) is None else [sp.get(key)]

    obj["couverture"].setdefault("notions_total", sum(len(sp.get("notions", [])) for sp in obj["sous_parties"]))
    obj["couverture"].setdefault("capacites_total", sum(len(sp.get("capacites_exigibles", [])) for sp in obj["sous_parties"]))
    obj["couverture"].setdefault("remarques", [])
    return obj


def ensure_exp_shape(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        obj = {}
    obj.setdefault("capacites_experimentales_communes", [])
    obj.setdefault("par_theme", {})
    for tid in ["constitution-matiere", "mouvement-interactions", "energie-conversions", "ondes-signaux"]:
        obj["par_theme"].setdefault(tid, [])
    return obj


def validate_minimum_blocks(themes: dict[str, dict[str, Any]]) -> list[str]:
    warnings = []
    for tid, theme in themes.items():
        expected = THEMES[tid]["minimum_blocks"]
        got = len(theme.get("sous_parties", []))
        if got < expected:
            warnings.append(f"{tid}: {got} blocs < minimum attendu {expected}")
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Structure le programme officiel depuis le PDF, avec découpage robuste par pages.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    if OUT_MAIN.exists() and not args.force:
        print(f"{OUT_MAIN} existe déjà. Utilise --force pour régénérer.")
        return

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY introuvable dans .env")

    sections = build_sections_from_pdf()

    print("Sections extraites depuis le PDF :")
    for tid in list(THEMES) + ["capacites-experimentales"]:
        print(f"- {tid}: {len(sections.get(tid, ''))} caractères")

    client = anthropic.Anthropic(api_key=api_key)

    structured_themes: dict[str, dict[str, Any]] = {}
    for tid in THEMES:
        print(f"\nStructuration : {tid}")
        obj = call_claude_json(
            client,
            prompt_theme(tid, sections[tid]),
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            max_retries=args.max_retries,
        )
        structured_themes[tid] = ensure_theme_shape(tid, obj)
        print(f"  -> OK ({len(structured_themes[tid].get('sous_parties', []))} blocs)")

    print("\nStructuration : capacités expérimentales")
    exp = call_claude_json(
        client,
        prompt_experimental(sections["capacites-experimentales"]),
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        max_retries=args.max_retries,
    )
    exp = ensure_exp_shape(exp)

    payload = {
        "source": str(PROGRAMME_PDF.relative_to(ROOT)),
        "version_pipeline": "programme-structure-pdf-pages-v3",
        "themes": [structured_themes[tid] for tid in THEMES],
        "capacites_experimentales": exp,
        "theme_index": {tid: THEMES[tid]["titre"] for tid in THEMES},
    }

    write_json(OUT_MAIN, payload)
    write_json(OUT_GENERATED, payload)

    warnings = validate_minimum_blocks(structured_themes)

    print("\nProgramme structuré écrit :")
    print(f"- {OUT_MAIN}")
    print(f"- {OUT_GENERATED}")
    print(f"- debug sections : {OUT_SECTIONS_DEBUG}")

    if warnings:
        print("\nATTENTION :")
        for w in warnings:
            print("-", w)
    else:
        print("\nStructure minimale cohérente.")


if __name__ == "__main__":
    main()
