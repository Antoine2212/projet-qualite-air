# Qualité de l'air à Paris

Peut-on prédire le niveau de pollution horaire au NO₂ à Paris à partir du trafic routier et de la météo ?

Projet Python, ENSAE 2026-2027.
Équipe : Victor Monfort, Mathis Marsoin, Antoine de Firmas.

## Lancer le projet

Tout le projet tient dans le notebook `project.ipynb`. Une connexion Internet est nécessaire : au premier lancement, le notebook copie les données brutes du trafic et de la qualité de l'air depuis SSP Cloud dans `data/` (dossiers publics, sans identifiant), refait leur nettoyage et interroge l'API Open-Meteo pour la météo.

### Sur son ordinateur

Prérequis : [Git](https://git-scm.com) et [uv](https://docs.astral.sh/uv/), qui installe aussi la bonne version de Python.

```bash
git clone https://github.com/Antoine2212/projet-qualite-air.git
cd projet-qualite-air
uv sync
```

`uv sync` crée l'environnement `.venv/` avec les versions exactes figées dans `uv.lock`. Ouvrir ensuite `project.ipynb` dans VS Code avec le kernel `.venv`, ou dans Jupyter avec `uv run --with jupyter jupyter lab`, puis exécuter toutes les cellules (« Run All »).

### Sur SSP Cloud (service Jupyter ou VS Code)

Dans un service lancé depuis [datalab.sspcloud.fr](https://datalab.sspcloud.fr), ouvrir un terminal (Jupyter : File → New → Terminal ; VS Code : Terminal → New Terminal) et lancer :

```bash
git clone https://github.com/Antoine2212/projet-qualite-air.git
cd projet-qualite-air
pip install -r requirements.txt
```

`pip` installe les librairies dans le Python du service : il n'y a pas de `.venv`. Ouvrir `project.ipynb` depuis l'explorateur de fichiers, garder le kernel Python par défaut (dans VS Code, le choisir via « Select Kernel »), puis « Run All ». Si le notebook était déjà ouvert avant le `pip install`, redémarrer le kernel.

### En cas d'erreur d'accès aux données

Hors de SSP Cloud (où les identifiants sont injectés automatiquement), copier `.env.example` en `.env` et le remplir depuis [Stockage de données](https://datalab.sspcloud.fr/s3) (détail du profil S3, section « Identifiants d'accès »). Ces identifiants expirent au bout de 7 jours. `.env` est ignoré par Git.

### Relancer les extractions

Les extractions depuis les sources d'origine ne sont pas relancées (≈1 h pour le trafic, ≈45 min pour la qualité de l'air). Pour les refaire, passer à `True` les variables `RELANCER_EXTRACTION_TRAFIC` et `RELANCER_EXTRACTION_AIR` en haut du notebook. L'API du trafic ne garde que les 13 derniers mois : une nouvelle extraction ne redonnerait pas exactement la même période.

## Structure

```
project.ipynb   notebook principal, de l'extraction à l'analyse
config.yaml     paramètres (période, seuils, rayons, adresses des sources et du stockage)
data/           données locales, ignorées par Git
src/            extraction, nettoyage, stockage, analyses
notebooks/      explorations détaillées par source (trafic, qualité de l'air)
reports/        figures
```

## Sources de données

Période étudiée : du 1er novembre 2025 au 30 septembre 2026 (`periode` dans `config.yaml`). Toutes les heures sont en UTC, à l'heure pleine, et marquent le début de la période mesurée.

### Trafic routier

[Comptage routier - Données trafic issues des capteurs permanents](https://opendata.paris.fr/explore/dataset/comptages-routiers-permanents/) et [Comptage routier - Référentiel géographique](https://opendata.paris.fr/explore/dataset/referentiel-comptages-routiers/), Ville de Paris (Direction de la Voirie et des Déplacements), licence [ODbL](https://opendatacommons.org/licenses/odbl/). Débit horaire (`q`, véhicules/h) et taux d'occupation (`k`, %) par arc de voirie, mesurés par boucles électromagnétiques ; le référentiel donne le tracé de chaque arc. Téléchargés par l'API Opendatasoft du portail, sans clé, un fichier par mois. Le jeu ne garde que les 13 derniers mois.

| Table (`data/interim/trafic/`) | Contenu |
|---|---|
| `trafic.parquet` | une ligne par (`iu_ac`, `heure`) : `q`, `k`, `libelle`, `longueur_m`, `x_centroide`, `y_centroide` (Lambert-93) ; grille complète, `NaN` quand la mesure manque |
| `referentiel_nettoye.parquet` | une ligne par arc gardé : `iu_ac`, tracé (`geometry`, Lambert-93), nœuds amont et aval |

### Qualité de l'air

[Mesures horaires LCSQA / Geod'air](https://www.data.gouv.fr/datasets/5b98b648634f415309d52a50), [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) : concentrations horaires des stations Airparif (NO₂, PM₂.₅, PM₁₀, O₃, NO, NOx), en UTC, avec leurs indicateurs de validité, plus les coordonnées des stations (« Dataset D »). Aucune clé d'API n'est nécessaire. Le flux WFS d'Airparif (projet DIDON) n'a pas été retenu, car ses couches de mesures ne gardent que les dernières 24 heures.

| Table (`data/interim/airparif/`) | Contenu |
|---|---|
| `mesures.parquet` | une ligne par (`station`, `heure`), une colonne par polluant en µg/m³ : `no2`, `pm25`, `pm10`, `o3`, `no`, `nox` |
| `stations.parquet` | `station`, `nom`, `influence` (trafic / fond), `implantation`, `latitude`, `longitude`, `polluants_mesures` |
| `anomalies.parquet` | valeurs suspectes : capteur figé (mise à NaN), pic isolé (gardée) |
| `decisions.csv` | chaque décision de nettoyage, avec le nombre de lignes concernées |

### Météo

[Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api), licence [CC BY 4.0](https://open-meteo.com/en/license) (données météo par Open-Meteo.com, issues des réanalyses ERA5 de Copernicus / ECMWF). Une seule série horaire pour Paris (48,8566° N ; 2,3522° E), en UTC, sans clé d'API : température, humidité, précipitations, pression, couverture nuageuse, vent à 10 m et 100 m (vitesse en km/h, direction en degrés), rafales, rayonnement. La réponse brute est enregistrée dans `data/raw/meteo/meteo.json`.

## Contribuer (équipe)

### Une fois, après avoir cloné

```bash
uv run nbstripout --install
```

Cette commande efface automatiquement les sorties des notebooks à chaque commit, ce qui évite les conflits. Le réglage est local : chacun doit la lancer sur sa machine.

### Données et SSP Cloud

Le code est sur GitHub, les données sur le stockage S3 de SSP Cloud, jamais dans Git. Les données brutes extraites y sont figées dans le dossier `diffusion` : les sources en ligne changent, la copie figée garantit que tout le monde, correcteur compris, travaille sur les mêmes données.

Chaque dataset est rangé dans l'espace SSP Cloud de la personne qui l'a extrait (`stockage.buckets` dans `config.yaml`) : seule elle peut l'envoyer, tout le monde peut le récupérer. L'envoi demande des identifiants (voir l'étape 3).

Chaque étape peut aussi se lancer en script, hors du notebook. Les scripts gardent en cache ce qu'ils ont déjà copié ou téléchargé : on peut les relancer sans risque.

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

Les contrôles détaillés de chaque source sont dans `notebooks/` : `qualite_air.ipynb`, `explo_trafic.ipynb` (exploration brute) et `analyse_trafic.ipynb`.

### Dépendances

Ajouter une librairie avec `uv add <nom>`, puis commiter `pyproject.toml` et `uv.lock`. Régénérer ensuite `requirements.txt`, utilisé sur SSP Cloud :

```bash
uv export --format requirements-txt --no-hashes --no-dev --no-emit-project -o requirements.txt
```
