from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def ensure_dirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_dicts(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def slugify(value: str, max_len: int = 80) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        value = "sujet"
    return value[:max_len].strip("-")


def normalize_space(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_pdf_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u000c", "\n")
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")
    # Artefacts fréquents dans certains PDF ministériels.
    text = text.replace("￾", "-")
    return normalize_space(text)


def extract_year_from_filename(name: str) -> int | None:
    m = re.search(r"(?:^|[^0-9])((?:20)?[0-9]{2})(?:[^0-9]|$)", name)
    if not m:
        return None
    y = int(m.group(1))
    if y < 100:
        y += 2000
    if 2000 <= y <= 2099:
        return y
    return None


def guess_session_from_filename(name: str) -> str:
    n = name.lower()
    if "j2" in n or "jour2" in n or "jour-2" in n:
        return "Jour 2"
    if "j1" in n or "jour1" in n or "jour-1" in n:
        return "Jour 1"
    if "rattrap" in n or "remplacement" in n:
        return "Remplacement"
    return "À préciser"


def site_relative(path: Path, site_root: Path) -> str:
    return path.resolve().relative_to(site_root.resolve()).as_posix()


def now_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def parse_json_object(text: str) -> Any:
    """Parse un objet JSON même si le modèle a ajouté du texte avant/après.

    Le prompt doit demander du JSON pur, mais cette fonction rend le pipeline moins fragile.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
    if fenced:
        return json.loads(fenced.group(1))

    start_candidates = [i for i in [text.find("{"), text.find("[")] if i != -1]
    if not start_candidates:
        raise ValueError("Aucun début d'objet JSON trouvé dans la réponse Claude.")
    start = min(start_candidates)
    end_obj = text.rfind("}")
    end_arr = text.rfind("]")
    end = max(end_obj, end_arr)
    if end <= start:
        raise ValueError("Aucune fin d'objet JSON trouvée dans la réponse Claude.")
    return json.loads(text[start : end + 1])


def detect_question_ids(text: str) -> list[str]:
    """Détecte les questions principales d'un exercice.

    Règle : si des questions Q1/Q2 existent, elles priment. Sinon on détecte les lignes numérotées
    1., 2., etc. Cette méthode n'est pas parfaite ; elle sert à déclencher une validation/révision.
    """
    text = text.replace("\r", "\n")
    q_matches = re.findall(r"(?m)^\s*(Q\s*\d{1,2})\s*[\.\)]", text, flags=re.I)
    if q_matches:
        seen: list[str] = []
        for q in q_matches:
            qid = re.sub(r"\s+", "", q.upper())
            if qid not in seen:
                seen.append(qid)
        return seen

    nums = []
    for m in re.finditer(r"(?m)^\s*(\d{1,2})\.\s+(?=\S)", text):
        n = int(m.group(1))
        # Évite les pages, codes ou numéros manifestement aberrants.
        if 1 <= n <= 30:
            nums.append(str(n))
    seen = []
    for n in nums:
        if n not in seen:
            seen.append(n)
    # Si l'on ne détecte qu'une seule section 1., c'est souvent un titre de partie, pas une question.
    return seen if len(seen) >= 2 else []


def first_nonempty_line(lines: Iterable[str]) -> str:
    for line in lines:
        line = line.strip()
        if line:
            return line
    return ""


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_break = cut.rfind("\n")
    if last_break > max_chars * 0.75:
        cut = cut[:last_break]
    return cut + "\n\n[TRONQUÉ POUR LE PROMPT — le texte brut complet reste dans data/raw/pages]"


def print_step(message: str) -> None:
    print(f"\n=== {message} ===", flush=True)


class PipelineError(RuntimeError):
    pass
