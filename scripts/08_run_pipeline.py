#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent


def run(cmd: list[str], dry_run: bool = False) -> None:
    printable = " ".join(cmd)
    print(f"\n$ {printable}")
    if dry_run:
        return
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Orchestre le pipeline complet de révision bac PC.")
    parser.add_argument("--programme-pdf", type=str, default=None, help="Chemin vers le PDF officiel du programme.")
    parser.add_argument("--limit-sujets", type=int, default=None, help="Limite pilote pour extraction/segmentation.")
    parser.add_argument("--limit-exercices", type=int, default=None, help="Limite pilote pour génération Claude des exercices.")
    parser.add_argument("--skip-programme", action="store_true", help="Ne régénère pas programme_officiel.json.")
    parser.add_argument("--skip-exercises", action="store_true", help="Ne régénère pas les exercices.")
    parser.add_argument("--skip-courses", action="store_true", help="Ne régénère pas les cours.")
    parser.add_argument("--force-programme", action="store_true", help="Force l'extraction/structuration du programme officiel.")
    parser.add_argument("--force-courses", action="store_true", help="Force la génération des cours.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    py = sys.executable

    if not args.skip_programme:
        cmd = [py, str(THIS_DIR / "00_extract_programme_officiel.py")]
        if args.programme_pdf:
            cmd += ["--pdf", args.programme_pdf]
        if args.force_programme:
            cmd += ["--force"]
        run(cmd, args.dry_run)

        cmd = [py, str(THIS_DIR / "00b_structure_programme_officiel.py")]
        if args.force_programme:
            cmd += ["--force"]
        run(cmd, args.dry_run)

    if not args.skip_exercises:
        run([py, str(THIS_DIR / "00_prepare_manifest.py")], args.dry_run)

        cmd = [py, str(THIS_DIR / "01_extract_pages.py")]
        if args.limit_sujets:
            cmd += ["--limit", str(args.limit_sujets)]
        run(cmd, args.dry_run)

        cmd = [py, str(THIS_DIR / "02_segment_exercises.py")]
        if args.limit_sujets:
            cmd += ["--limit", str(args.limit_sujets)]
        run(cmd, args.dry_run)

        cmd = [py, str(THIS_DIR / "03_generate_exercises.py")]
        if args.limit_exercices:
            cmd += ["--limit", str(args.limit_exercices)]
        run(cmd, args.dry_run)

    run([py, str(THIS_DIR / "04_validate.py")], args.dry_run)

    if not args.skip_courses:
        cmd = [py, str(THIS_DIR / "05_generate_courses.py")]
        if args.force_courses:
            cmd += ["--force"]
        run(cmd, args.dry_run)

    run([py, str(THIS_DIR / "07_generate_quiz.py")], args.dry_run)
    run([py, str(THIS_DIR / "06_build_site_data.py")], args.dry_run)
    run([py, str(THIS_DIR / "04_validate.py")], args.dry_run)


if __name__ == "__main__":
    main()
