#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import shutil
import sys


def project_root_from_manifest(manifest_path: Path) -> Path:
    # manifest: <root>/site/data/manifest.csv
    try:
        return manifest_path.resolve().parents[2]
    except Exception:
        return Path.cwd()


def image_to_pdf_stem(image_path: Path) -> str:
    """
    Convert image filename created in pages_a_identifier back to the original PDF stem.

    Examples:
      24_24-pycg11bisv1pdf-106395_page1.png -> 24-pycg11bisv1pdf-106395
      52_baccalaur-g-n-ral-2022-physique-chimie-1142450pdf-96402_page1.png
         -> baccalaur-g-n-ral-2022-physique-chimie-1142450pdf-96402
    """
    stem = image_path.stem

    # Remove leading index prefix "NN_" if present
    if "_" in stem:
        first, rest = stem.split("_", 1)
        if first.isdigit():
            stem = rest

    # Remove trailing page marker
    for suffix in ["_page1", "_page_1", "_page01", "_page_01"]:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    return stem


def backup_file(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".{ts}.bak")
    shutil.copy2(path, backup)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Désactive dans manifest.csv les sujets dont la première page a été exportée dans pages_a_identifier."
    )
    parser.add_argument(
        "--manifest",
        default="site/data/manifest.csv",
        help="Chemin vers manifest.csv (défaut: site/data/manifest.csv)",
    )
    parser.add_argument(
        "--images-dir",
        default="site/data/rapports/pages_a_identifier",
        help="Dossier contenant les PNG de pages à identifier (défaut: site/data/rapports/pages_a_identifier)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les désactivations prévues sans modifier manifest.csv",
    )
    parser.add_argument(
        "--only-enabled",
        action="store_true",
        help="Ne désactive que les lignes actuellement à enabled=1",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    images_dir = Path(args.images_dir)

    if not manifest_path.exists():
        print(f"ERREUR manifest introuvable : {manifest_path}")
        return 1
    if not images_dir.exists():
        print(f"ERREUR dossier images introuvable : {images_dir}")
        return 1

    png_files = sorted(images_dir.glob("*.png"))
    if not png_files:
        print(f"Aucun PNG trouvé dans : {images_dir}")
        return 1

    target_stems = {image_to_pdf_stem(png) for png in png_files}

    with manifest_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            print("ERREUR: manifest.csv vide ou invalide")
            return 1
        rows = list(reader)

    if "enabled" not in fieldnames or "pdf_path" not in fieldnames:
        print("ERREUR: le manifest doit contenir au minimum les colonnes 'enabled' et 'pdf_path'")
        return 1

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    to_disable = []

    for idx, row in enumerate(rows, start=2):  # header is line 1
        pdf_stem = Path(row.get("pdf_path", "")).stem
        if pdf_stem in target_stems:
            current_enabled = str(row.get("enabled", "")).strip()
            if args.only_enabled and current_enabled != "1":
                continue
            to_disable.append((idx, row))

    if not to_disable:
        print("Aucune ligne du manifest ne correspond aux fichiers présents dans pages_a_identifier.")
        print(f"PNG détectés : {len(png_files)}")
        return 0

    print(f"Fichiers PNG détectés dans {images_dir}: {len(png_files)}")
    print(f"Lignes du manifest à désactiver : {len(to_disable)}\n")

    for line_no, row in to_disable:
        print(f"- ligne {line_no}: {row.get('pdf_path','')} | enabled={row.get('enabled','')} | id={row.get('id','')}")

    if args.dry_run:
        print("\nMode dry-run: aucune modification écrite.")
        return 0

    backup = backup_file(manifest_path)

    for _, row in to_disable:
        row["enabled"] = "0"
        note = (row.get("notes") or "").strip()
        addition = f"Désactivé automatiquement le {now} car présent dans pages_a_identifier."
        if note:
            if addition not in note:
                row["notes"] = note + " " + addition
        else:
            row["notes"] = addition

    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("\nBackup créé :", backup)
    print("Manifest mis à jour :", manifest_path)
    print(f"Total désactivé : {len(to_disable)}")

    root = project_root_from_manifest(manifest_path)
    print("\nCommande de contrôle suggérée :")
    print("python - <<'PY'")
    print("import csv")
    print("from pathlib import Path")
    print("rows = list(csv.DictReader(Path('site/data/manifest.csv').open(encoding='utf-8')))")
    print("print('Sujets activés :', sum(1 for r in rows if r.get('enabled') == '1'))")
    print("print('Sujets désactivés :', sum(1 for r in rows if r.get('enabled') == '0'))")
    print("PY")

    return 0


if __name__ == "__main__":
    sys.exit(main())
