#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
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
GENERATED_EX_DIR = DATA / "generated" / "exercises"
BACKUP_ROOT = DATA / "generated" / "exercises_latex_backup"
REPORTS_DIR = DATA / "rapports"

if load_dotenv:
    load_dotenv(ROOT / ".env")

DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS_LATEX", os.getenv("CLAUDE_MAX_TOKENS", "32000")))
DEFAULT_TEMPERATURE = float(os.getenv("CLAUDE_TEMPERATURE_LATEX", "0"))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


def count_latex_markers(obj: Any) -> dict[str, int]:
    s = json.dumps(obj, ensure_ascii=False)
    return {
        "dollars": s.count("$"),
        "display_dollars": s.count("$$"),
        "backslash": s.count("\\"),
        "frac": s.count("\\frac"),
        "vec": s.count("\\vec"),
        "bracket_display": s.count("\\[") + s.count("\\]"),
        "paren_inline": s.count("\\(") + s.count("\\)"),
    }


def extract_relevant_payload(ex: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ex.get("id"),
        "titre": ex.get("titre"),
        "aide": ex.get("aide", []),
        "corrige": ex.get("corrige", {}),
    }


def merge_normalized(original: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    out = dict(original)
    out["aide"] = normalized.get("aide", original.get("aide", []))
    out["corrige"] = normalized.get("corrige", original.get("corrige", {}))
    meta = dict(out.get("_normalisation_latex") or {})
    meta.update({
        "status": "done",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "script": "07_normalize_latex_exercises.py",
    })
    out["_normalisation_latex"] = meta
    return out


def validate_shape(original: dict[str, Any], normalized: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(normalized, dict):
        return ["reponse_non_dict"]
    if normalized.get("id") != original.get("id"):
        errors.append("id_modifie")
    if "aide" not in normalized or not isinstance(normalized.get("aide"), list):
        errors.append("aide_absente_ou_non_liste")
    corrige = normalized.get("corrige")
    if not isinstance(corrige, dict):
        errors.append("corrige_non_dict")
    else:
        q_orig = ((original.get("corrige") or {}).get("questions") or []) if isinstance(original.get("corrige"), dict) else []
        q_new = corrige.get("questions") or []
        if not isinstance(q_new, list):
            errors.append("corrige_questions_non_liste")
        elif len(q_new) != len(q_orig):
            errors.append(f"nombre_questions_modifie:{len(q_orig)}->{len(q_new)}")
        else:
            for i, (qo, qn) in enumerate(zip(q_orig, q_new), start=1):
                if str(qo.get("numero", "")) != str(qn.get("numero", "")):
                    errors.append(f"numero_question_modifie:{i}:{qo.get('numero')}->{qn.get('numero')}")
                    break
    return errors


def prompt_for_exercise(ex: dict[str, Any]) -> str:
    payload = extract_relevant_payload(ex)
    return f"""
Tu dois normaliser le LaTeX dans un exercice de physique-chimie du baccalauréat.

TÂCHE STRICTE :
- Ne modifie PAS le raisonnement.
- Ne modifie PAS les valeurs numériques.
- Ne modifie PAS les unités, sauf si nécessaire pour écrire une formule propre.
- Ne modifie PAS les numéros de questions.
- Ne modifie PAS le nombre de questions.
- Ne modifie PAS la structure JSON.
- Ne reformule pas inutilement les phrases.
- Corrige uniquement l'écriture des formules mathématiques, physiques et chimiques.

RÈGLES LATEX :
- Toute formule en ligne doit être entre $...$.
- Toute formule longue, équation de réaction, expression développée ou calcul important doit être entre $$...$$.
- Aucune commande LaTeX ne doit apparaître hors délimiteurs.
- Utilise un LaTeX compatible KaTeX.
- N'utilise jamais \\cdotp ; utilise toujours \\cdot pour le point de multiplication.
- IMPORTANT JSON : tous les antislashs LaTeX doivent être échappés dans le JSON.
  Exemple : écris "$\\tau = RC$" et non "$\tau = RC$".
  Exemple : écris "$$Q = \\frac{{a}}{{b}}$$" et non "$$Q = \frac{{a}}{{b}}$$".
- Remplace les écritures hybrides comme m·\\vec{{a}} = m·\\vec{{g}} par du LaTeX délimité, par exemple $m \\cdot \\vec{{a}} = m \\cdot \\vec{{g}}$.
- Remplace les blocs \\[ ... \\] par $$ ... $$.
- Remplace les blocs \\( ... \\) par $ ... $.
- Garde les unités lisibles. Exemple accepté : $m \\cdot s^{{-2}}$ ou texte Unicode si ce n'est pas une formule centrale.
- Les équations chimiques peuvent être en texte simple si elles sont déjà lisibles, ou en LaTeX délimité si elles contiennent des indices/exposants.

FORMAT DE SORTIE :
Retourne uniquement un JSON valide, sans Markdown, avec exactement ces clés racine :
{{
  "id": "...",
  "titre": "...",
  "aide": [...],
  "corrige": {{
    "questions": [...]
  }}
}}

JSON À NORMALISER :
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()


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
                    "Tu es un relecteur scientifique expert en physique-chimie et en LaTeX KaTeX. "
                    "Tu corriges uniquement la syntaxe LaTeX dans des JSON existants."
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
    raise RuntimeError(f"Échec normalisation LaTeX : {last_error}")


def select_files(limit: int | None, only_ids: set[str] | None, force: bool) -> list[Path]:
    files = sorted(GENERATED_EX_DIR.glob("*.json"))
    selected: list[Path] = []
    for p in files:
        ex = read_json(p)
        if only_ids and ex.get("id") not in only_ids:
            continue
        if not force and isinstance(ex, dict) and (ex.get("_normalisation_latex") or {}).get("status") == "done":
            continue
        selected.append(p)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def load_ids_file(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.add(line)
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalise le LaTeX des aides et corrigés des exercices générés.")
    parser.add_argument("--limit", type=int, default=None, help="Nombre d'exercices à traiter.")
    parser.add_argument("--force", action="store_true", help="Retraiter même les exercices déjà normalisés.")
    parser.add_argument("--dry-run", action="store_true", help="Prévisualise les fichiers sélectionnés sans appeler Claude.")
    parser.add_argument("--ids-file", type=Path, default=None, help="Fichier contenant une liste d'IDs à traiter.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    if not GENERATED_EX_DIR.exists():
        raise FileNotFoundError(f"Dossier introuvable : {GENERATED_EX_DIR}")

    only_ids = load_ids_file(args.ids_file)
    files = select_files(args.limit, only_ids, args.force)

    print(f"Projet : {ROOT}")
    print(f"Dossier exercices : {GENERATED_EX_DIR}")
    print(f"Modèle Claude : {args.model}")
    print(f"Max tokens : {args.max_tokens}")
    print(f"Exercices sélectionnés : {len(files)}")

    if not files:
        print("Aucun exercice à traiter.")
        return

    for p in files:
        ex = read_json(p)
        print("-", ex.get("id"), "|", ex.get("titre"))

    if args.dry_run:
        print("Dry-run : aucun appel Claude.")
        return

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY introuvable dans .env")

    client = anthropic.Anthropic(api_key=api_key)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    report_rows: list[dict[str, Any]] = []

    for i, p in enumerate(files, start=1):
        original = read_json(p)
        ex_id = original.get("id")
        print(f"\n[{i}/{len(files)}] {ex_id} — {original.get('titre')}")
        before_counts = count_latex_markers(extract_relevant_payload(original))
        backup_path = backup_dir / p.name
        shutil.copy2(p, backup_path)
        try:
            normalized_payload = call_claude_json(
                client,
                prompt_for_exercise(original),
                model=args.model,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                max_retries=args.max_retries,
            )
            errors = validate_shape(original, normalized_payload)
            if errors:
                print("  -> ERREUR validation :", " | ".join(errors))
                report_rows.append({"id": ex_id, "status": "validation_error", "errors": " | ".join(errors), "file": str(p), "backup": str(backup_path)})
                continue
            updated = merge_normalized(original, normalized_payload)
            after_counts = count_latex_markers(extract_relevant_payload(updated))
            write_json(p, updated)
            print("  -> OK")
            print(f"     dollars: {before_counts['dollars']} -> {after_counts['dollars']}")
            print(f"     backslash: {before_counts['backslash']} -> {after_counts['backslash']}")
            report_rows.append({
                "id": ex_id,
                "status": "ok",
                "errors": "",
                "file": str(p),
                "backup": str(backup_path),
                "dollars_before": before_counts["dollars"],
                "dollars_after": after_counts["dollars"],
                "backslash_before": before_counts["backslash"],
                "backslash_after": after_counts["backslash"],
            })
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print("  -> ERREUR :", exc)
            report_rows.append({"id": ex_id, "status": "error", "errors": str(exc), "file": str(p), "backup": str(backup_path)})

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"latex_normalization_{stamp}.json"
    write_json(report_path, {"timestamp": stamp, "model": args.model, "max_tokens": args.max_tokens, "backup_dir": str(backup_dir), "rows": report_rows})

    print("\nNormalisation terminée.")
    print("Backup :", backup_dir)
    print("Rapport :", report_path)
    print("\nÉtape suivante recommandée :")
    print("python scripts/06_build_site_data.py --force")


if __name__ == "__main__":
    main()
