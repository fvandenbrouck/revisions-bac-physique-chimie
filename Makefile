.PHONY: setup check-env pilot validate courses build repair-mermaid

setup:
	python3 scripts/00_setup_project.py

check-env:
	python3 scripts/11_check_env.py

pilot:
	python3 scripts/00_prepare_manifest.py
	python3 scripts/01_extract_pages.py --limit 5
	python3 scripts/02_segment_exercises.py --limit 5
	python3 scripts/03_generate_exercises.py --limit 20
	python3 scripts/04_validate.py

validate:
	python3 scripts/04_validate.py
	python3 scripts/10_programme_coverage_report.py

courses:
	python3 scripts/05_generate_courses.py --force
	python3 scripts/10_programme_coverage_report.py

build:
	python3 scripts/07_generate_quiz.py
	python3 scripts/06_build_site_data.py

repair-mermaid:
	python3 scripts/09_repair_mermaid.py --backup
