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

La période et les autres paramètres se règlent dans `config.yaml`. Chaque script garde en cache ce qu'il a déjà téléchargé : on peut le relancer sans risque, il ne récupère que les morceaux manquants.

```bash
uv run python -m src.extract.meteo      # quelques secondes
uv run python -m src.extract.airparif   # ~30 min (un fichier par jour)
uv run python -m src.extract.trafic     # ~1 h (2,2 millions de lignes par mois)
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

| Source | Contenu | Accès | Licence | Fichiers bruts |
|---|---|---|---|---|
| [Mesures horaires LCSQA / Geod'air](https://www.data.gouv.fr/datasets/5b98b648634f415309d52a50) | Concentrations horaires des stations Airparif (NO₂, PM₂.₅, PM₁₀, O₃…), en UTC, avec indicateurs de validité ; métadonnées des stations (« Dataset D ») | Un CSV national par jour, depuis 2021 | Licence Ouverte 2.0 | `data/raw/airparif/mesures_AAAA-MM-JJ.csv`, `stations_dataset_D.xls` |
| [Comptages routiers permanents](https://opendata.paris.fr/explore/dataset/comptages-routiers-permanents/) et [référentiel](https://opendata.paris.fr/explore/dataset/referentiel-comptages-routiers/), Ville de Paris | Débit (`q`, véhicules/h) et taux d'occupation (`k`, %) par arc (`iu_ac`) | API Opendatasoft, 13 derniers mois | ODbL | `data/raw/trafic/comptages_<début>_<fin>.parquet`, `referentiel_arcs.json` |
| [Open-Meteo Historical Weather](https://open-meteo.com/en/docs/historical-weather-api) | Température, humidité, pluie, pression, vent (m/s, direction) | API REST sans clé | CC BY 4.0 | `data/raw/meteo/meteo_<début>_<fin>.json` |

Pourquoi pas le WFS Airparif (projet DIDON) ? Ses couches de mesures ne gardent que les dernières 24 heures (elles étaient vides lors du test du 2026-10-18). Les fichiers du LCSQA reprennent les mêmes mesures Airparif avec tout l'historique. Les stations Airparif y sont repérées par l'organisme `AIRPARIF` et des codes `FR04xxx`.

Conventions à traiter au nettoyage :
- Airparif (LCSQA) : heures en UTC, horodatage en **début** de période (`Date de début`).
- Trafic : demandé en UTC (`timezone=UTC`), mais `t_1h` marque la **fin** de la période de comptage.
- Météo : demandée en UTC, valeur instantanée à l'heure pile (cumul sur l'heure précédente pour la pluie).

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