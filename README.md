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
git clone https://github.com/Antoine2212/projet-qualite-air.git
cd projet-qualite-air
uv sync
```

`uv sync` crée l'environnement `.venv/` avec les versions exactes figées dans `uv.lock`.

Dans VS Code, vous pouvez aussi passer par `Ctrl+Shift+P` → **Git: Clone**, puis lancer `uv sync` dans le terminal du projet.

### Sur SSP Cloud (test de rendu)

Dans un nouveau service VS Code ou Jupyter de [datalab.sspcloud.fr](https://datalab.sspcloud.fr) :

```bash
git clone https://github.com/Antoine2212/projet-qualite-air.git
cd projet-qualite-air
pip install -r requirements.txt
```

`requirements.txt` est généré depuis `uv.lock` : après chaque `uv add`, le régénérer avec
`uv export --format requirements-txt --no-hashes --no-dev --no-emit-project -o requirements.txt`.

### Notebooks

Choisissez le kernel `.venv` du projet dans VS Code, ou lancez :

```bash
uv run --with jupyter jupyter lab
```

## Lancer l'analyse

Le code est sur GitHub, les données sur le stockage S3 de SSP Cloud, jamais dans Git.
Les données brutes extraites y sont figées dans le dossier `diffusion`, lisible par tous les
utilisateurs de la plateforme : les sources en ligne changent, la copie figée garantit que
tout le monde, correcteur compris, travaille sur les mêmes données.

La période, les seuils et l'emplacement du stockage se règlent dans `config.yaml`. Les scripts
gardent en cache ce qu'ils ont déjà copié ou téléchargé : on peut les relancer sans risque.

Chaque dataset est rangé dans l'espace SSP Cloud de la personne qui l'a extrait
(`stockage.buckets` dans `config.yaml`) : seule elle peut l'envoyer, tout le monde peut le récupérer.

```bash
uv run python -m src.stockage recuperer   # récupère tous les datasets depuis SSP Cloud

# Qualité de l'air (Airparif)
uv run python -m src.extract.airparif                     # extraction depuis la source, ~45 min la première fois
uv run python -m src.stockage envoyer --dataset airparif  # fige data/ sur SSP Cloud (Mathis)
uv run python -m src.stockage recuperer --dataset airparif
uv run python -m src.clean.airparif                       # nettoyage, écrit data/interim/airparif/

# Trafic routier (Ville de Paris)
uv run python -m src.extract.trafic                       # extraction depuis la source, ~1 h la première fois
uv run python -m src.stockage envoyer --dataset trafic    # fige data/ sur SSP Cloud (Antoine)
uv run python -m src.stockage recuperer --dataset trafic
uv run python -m src.clean.trafic                         # nettoyage, écrit data/interim/trafic/
```

**Identifiants SSP Cloud.** Dans un service SSP Cloud, ils sont injectés automatiquement.
Ailleurs, copier `.env.example` en `.env` et le remplir depuis
[Stockage de données](https://datalab.sspcloud.fr/s3) (détail du profil S3, section « Identifiants d'accès ») ;
ils expirent au bout de 7 jours.
`.env` est ignoré par Git : aucun identifiant ne doit être commité.

Le notebook `qualite_air.ipynb` récupère les données brutes depuis SSP Cloud, refait le nettoyage
et montre les contrôles. Il tourne de haut en bas (« Run All ») sans relancer l'extraction.

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

À compléter pour le trafic (Ville de Paris) et la météo (Open-Meteo).

**Qualité de l'air.** [Mesures horaires LCSQA / Geod'air](https://www.data.gouv.fr/datasets/5b98b648634f415309d52a50) (Licence Ouverte 2.0) : concentrations horaires des stations Airparif (NO₂, PM₂.₅, PM₁₀, O₃, NO, NOx), en UTC, avec leurs indicateurs de validité, plus les coordonnées des stations (« Dataset D »). Aucune clé d'API n'est nécessaire. Le flux WFS d'Airparif (projet DIDON) n'a pas été retenu, car ses couches de mesures ne gardent que les dernières 24 heures.

| Table (`data/interim/airparif/`) | Contenu |
|---|---|
| `mesures.parquet` | une ligne par (`station`, `heure` UTC, début de période), une colonne par polluant en µg/m³ : `no2`, `pm25`, `pm10`, `o3`, `no`, `nox` |
| `stations.parquet` | `station`, `nom`, `influence` (trafic / fond), `implantation`, `latitude`, `longitude`, `polluants_mesures` |
| `anomalies.parquet` | valeurs suspectes : capteur figé (mise à NaN), pic isolé (gardée) |
| `decisions.csv` | chaque décision de nettoyage, avec le nombre de lignes concernées |

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