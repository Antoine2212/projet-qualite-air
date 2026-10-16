# Qualité de l'air à Paris

Peut-on prédire le niveau de pollution horaire au NO₂ à Paris à partir du trafic routier et de la météo ?

Projet Python, ENSAE 2026-2027.
Équipe : Victor Monfort, Mathis Marsoin, Antoine de Firmas.

## Installation

### Prérequis

- [Git](https://git-scm.com)
- [uv](https://docs.astral.sh/uv/), qui installe aussi la bonne version de Python

### Récupérer le projet

```bash
git clone https://github.com/[compte]/projet-qualite-air.git
cd projet-qualite-air
uv sync
```

`uv sync` crée l'environnement `.venv/` avec les versions exactes figées dans `uv.lock`.

Dans VS Code, vous pouvez aussi passer par `Ctrl+Shift+P` → **Git: Clone**, puis lancer `uv sync` dans le terminal du projet.

### Notebooks

Choisissez le kernel `.venv` du projet dans VS Code, ou lancez :

```bash
uv run --with jupyter jupyter lab
```

## Lancer l'analyse

Les données ne sont pas versionnées. Les scripts les téléchargent dans `data/raw/`, puis produisent `data/interim/` et `data/processed/`.

```bash
# À compléter quand les scripts existent, par exemple :
uv run python -m src.extract.meteo
```

Ensuite, exécutez les notebooks dans l'ordre (`01` à `04`).

## Structure

```
config.yaml   paramètres (période, stations, rayon, seuils)
data/         données locales, ignorées par Git
src/          extraction, nettoyage, fusion, variables, modèles
notebooks/    analyse, de 01 à 04
reports/      rapport et figures
```

## Sources de données

À compléter avec les liens et les licences : Airparif Open Data, comptages routiers de la Ville de Paris, Open-Meteo.

## Contribuer (équipe)

### Une fois, après avoir cloné

```bash
uv run nbstripout --install
```

Cette commande efface automatiquement les sorties des notebooks à chaque commit, ce qui évite les conflits. Le réglage est local : chacun doit la lancer sur sa machine.

### Routine

1. Se placer sur `main` et faire **Pull**.
2. Créer une branche par tâche (`extraction-meteo`, `nettoyage-trafic`…). Personne ne travaille directement sur `main`.
3. Faire de petits commits avec des messages clairs, puis **Publish Branch** ou **Sync**.
4. Ouvrir une pull request sur GitHub. Un autre membre relit, puis fusionne.

### Règles

- Ajouter une librairie avec `uv add <nom>`, jamais avec `pip install`, puis commiter `pyproject.toml` et `uv.lock`.
- Un notebook n'a qu'un seul auteur à la fois.
- Aucune donnée, clé d'API ni fichier `.env` dans Git.
- Tous les paramètres vont dans `config.yaml`, pas en dur dans le code.