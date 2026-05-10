# Révision Bac Physique-Chimie — site autonome

## Ce qui a été corrigé

1. **Énoncés visibles sans serveur**  
   La modale n'utilise plus un `iframe` PDF, trop fragile en ouverture directe (`file://`) et selon les navigateurs. Elle affiche désormais les **pages PNG rendues depuis les PDF** : `img/<sujet>/page_XX.png`.

2. **Données 2022 remises en cohérence avec le PDF fourni**  
   L'ancien paquet mélangeait un sujet 2022 « Ingenuity » avec un autre PDF. Le nouveau jeu de données correspond au sujet `22-PYCJ1ME3` : acide méthanoïque, Saturne, ISS, fil de suture.

3. **Corrigés complétés**  
   Les 8 exercices des deux sujets fournis disposent maintenant d'un corrigé développé, question par question.

4. **Aucun backend requis**  
   `proxy.py` n'est plus nécessaire. Le quiz est local. La génération Claude reste dans le pipeline Python, mais pas dans le navigateur.

5. **Chargement robuste des données**  
   `index.html` tente de charger `data/data.json`. Si le navigateur bloque `fetch` en ouverture directe, il utilise une copie embarquée des données. Les images restent chargées depuis les fichiers locaux.

## Lancer le site

### Option 1 — ouverture directe

Ouvrir simplement :

```bash
site/index.html
```

C'est l'option la plus simple. Les exercices, corrigés, cours et images fonctionnent.

### Option 2 — mini-serveur local conseillé pour développer

Depuis le dossier `site/` :

```bash
python3 -m http.server 8000
```

Puis ouvrir :

```text
http://localhost:8000
```

Cette option permet de tester le chargement réel de `data/data.json`.

## Arborescence

```text
site/
├── index.html
├── README.md
├── data/
│   ├── data.json          # données combinées utilisées par index.html
│   ├── programme.json
│   ├── exercices.json
│   ├── cours.json
│   └── quiz.json
├── img/
│   ├── 2021-j1/
│   └── 2022-j1/
├── pdf/
│   ├── 2021-j1.pdf
│   └── 2022-j1.pdf
└── scripts/
    ├── 01_extraire_programme.py
    ├── 02_extraire_exercices.py
    └── 03_classifier_et_generer.py
```

## Régénérer les images et les textes bruts depuis les PDF

Depuis `site/` :

```bash
python3 scripts/02_extraire_exercices.py pdf/2021-j1.pdf pdf/2022-j1.pdf
```

Le script produit :

```text
data/brut/*.json
img/<slug>/page_XX.png
```

## Régénérer les contenus avec Claude

Définir la clé API :

```bash
export ANTHROPIC_API_KEY="..."
```

Puis :

```bash
python3 scripts/03_classifier_et_generer.py
```

Le script refuse d'écrire les fichiers si le JSON est invalide ou si un corrigé est manifestement trop court.

## Point de vigilance

Le site est autonome pour la consultation. En revanche, la **génération automatique de nouveaux corrigés par Claude** ne doit pas se faire dans le navigateur : cela exposerait la clé API. Elle doit rester dans le pipeline Python local.
