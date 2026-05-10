# Projet de révision Bac Physique-Chimie — pipeline local

Ce dossier est prévu pour être décompressé dans :

```bash
/Users/francoisvandenbrouck/Documents/FV/perso/bac/pc
```

Le fichier `.env` doit être placé à la racine de ce dossier, jamais dans `site/`.

## 0. Structure attendue

```text
pc/
├── .env                  # à créer localement ; jamais à pousser sur GitHub
├── .env.example
├── .gitignore
├── requirements.txt
├── README_WORKFLOW.md
├── scripts/              # pipeline Python
└── site/                 # site statique HTML/CSS/JS + données
    ├── index.html
    ├── data/
    ├── img/
    ├── pdf/
    └── programme/
```

Les scripts créent automatiquement les sous-dossiers manquants dans `site/`.

## 1. Créer le fichier `.env`

Depuis la racine du projet :

```bash
cd /Users/francoisvandenbrouck/Documents/FV/perso/bac/pc

cat > .env <<'EOF'
ANTHROPIC_API_KEY=VOTRE_CLE_ANTHROPIC_ICI
CLAUDE_MODEL=claude-sonnet-4-6
CLAUDE_MAX_TOKENS=64000
CLAUDE_TEMPERATURE=0.1
EOF

chmod 600 .env
```

Ne jamais commiter `.env`.

## 2. Créer l'environnement Python

```bash
cd /Users/francoisvandenbrouck/Documents/FV/perso/bac/pc
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Vérifier l'architecture et la configuration

```bash
python3 scripts/00_setup_project.py
python3 scripts/11_check_env.py
```

## 4. Ajouter les fichiers sources

Mettre le programme officiel ici :

```text
site/programme/Terminale PC.pdf
```

Mettre les 71 sujets PDF ici :

```text
site/pdf/
```

## 5. Structurer le programme officiel

```bash
python3 scripts/00_extract_programme_officiel.py --pdf "site/programme/Terminale PC.pdf" --force
python3 scripts/00b_structure_programme_officiel.py --force
```

Sorties principales :

```text
site/data/programme_officiel_raw.json
site/data/programme_officiel.json
```

## 6. Traitement pilote recommandé

Ne pas commencer par 71 sujets. Tester d'abord sur 5 sujets.

```bash
python3 scripts/00_prepare_manifest.py
python3 scripts/01_extract_pages.py --limit 5
python3 scripts/02_segment_exercises.py --limit 5
python3 scripts/03_generate_exercises.py --limit 20
python3 scripts/04_validate.py
```

Regarder :

```text
site/data/rapports/validation.csv
```

## 7. Générer les cours exhaustifs à partir du programme

Les cours ne sont pas générés à partir des sujets. Les sujets servent d'exemples ; le référentiel reste le programme officiel.

```bash
python3 scripts/05_generate_courses.py --force
python3 scripts/10_programme_coverage_report.py
```

Le fichier critique est :

```text
site/data/rapports/programme_coverage.csv
```

Tant qu'une ligne est marquée `manquant`, le cours n'est pas exhaustif.

## 8. Traitement complet

Quand le pilote est stable :

```bash
python3 scripts/01_extract_pages.py
python3 scripts/02_segment_exercises.py
python3 scripts/03_generate_exercises.py
python3 scripts/04_validate.py
python3 scripts/05_generate_courses.py --force
python3 scripts/10_programme_coverage_report.py
python3 scripts/07_generate_quiz.py
python3 scripts/06_build_site_data.py
python3 scripts/04_validate.py
```

## 9. Corriger les cartes mentales Mermaid

Les cartes mentales sont générées à partir d'une structure JSON, puis converties en Mermaid sûr.

Pour réparer les cartes existantes :

```bash
python3 scripts/09_repair_mermaid.py --backup
```

## 10. GitHub

La clé API est protégée par `.gitignore`. Avant le premier push :

```bash
git init
git status
git add .
git commit -m "Initial commit - site revision bac physique chimie"
```

Il faudra créer ou indiquer le dépôt exact. L'URL fournie `https://github.com/fvandenbrouck/` est une page de compte, pas l'URL d'un dépôt. L'URL de remote aura la forme :

```bash
git remote add origin https://github.com/fvandenbrouck/NOM_DU_DEPOT.git
git branch -M main
git push -u origin main
```

## 11. Règles de sécurité

- Ne pas pousser `.env`.
- Ne pas afficher la clé API dans les captures d'écran.
- Vérifier `git status` avant chaque push.
- Relire les corrigés signalés par `validation.csv` avant diffusion.
