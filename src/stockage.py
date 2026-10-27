"""Synchronisation du dossier data/ avec le stockage S3 de SSP Cloud (MinIO).

Le code vit sur GitHub, les données sur SSP Cloud. Chaque dataset (airparif, trafic…) est
rangé dans l'espace de la personne qui l'a extrait, car chacun ne peut écrire que dans le sien
(voir stockage.buckets dans config.yaml) :
- envoyer   : copie data/<étape>/<dataset>/ vers s3://<bucket du dataset>/<dossier>/<étape>/<dataset>/
- recuperer : copie dans l'autre sens, pour qui n'a pas relancé l'extraction

Seuls les fichiers absents ou de taille différente sont copiés : on peut relancer sans risque.

Identifiants : jamais dans le code ni dans Git. Ils viennent des variables d'environnement
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN et AWS_S3_ENDPOINT,
injectées automatiquement dans les services SSP Cloud. Sur un autre ordinateur, les copier
depuis https://datalab.sspcloud.fr/s3 (menu « Stockage de données », détail du profil S3)
dans un fichier .env (voir .env.example).
Ils expirent au bout de 7 jours.

Lancement :
  uv run python -m src.stockage envoyer --dataset trafic    # dans son propre espace seulement
  uv run python -m src.stockage recuperer --dataset trafic
  uv run python -m src.stockage recuperer                   # tous les datasets
"""

import argparse
import logging
import os
import time

import s3fs
from dotenv import load_dotenv
from tqdm.auto import tqdm

from src.utils import RACINE, charger_config, configurer_logs

log = logging.getLogger(__name__)

VARIABLES = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_S3_ENDPOINT")


def connecter() -> s3fs.S3FileSystem:
    """Ouvre le stockage SSP Cloud à partir des variables d'environnement (ou de .env)."""
    load_dotenv(RACINE / ".env")
    manquantes = [v for v in VARIABLES if not os.environ.get(v)]
    if manquantes:
        raise RuntimeError(
            f"Identifiants SSP Cloud absents ({', '.join(manquantes)}). Lance le script depuis un "
            "service SSP Cloud, ou copie-les depuis https://datalab.sspcloud.fr/s3 (détail du profil S3) "
            "dans un fichier .env à la racine du projet."
        )
    # s3fs lit lui-même les clés dans l'environnement ; il ne lui manque que l'adresse du serveur.
    return s3fs.S3FileSystem(client_kwargs={"endpoint_url": f"https://{os.environ['AWS_S3_ENDPOINT']}"})


def racine_distante(config: dict, dataset: str) -> str:
    """Dossier SSP Cloud du dataset : <bucket de son propriétaire>/<dossier>."""
    buckets = config["stockage"]["buckets"]
    if dataset not in buckets:
        raise ValueError(f"Dataset inconnu : {dataset}. Datasets dans config.yaml : {', '.join(buckets)}")
    return f"{buckets[dataset]}/{config['stockage']['dossier']}"


def fichiers_locaux(config: dict, dataset: str) -> dict[str, int]:
    """Fichiers du dataset dans data/, sous la forme {chemin relatif à data/ : taille}."""
    data = RACINE / "data"
    fichiers = {}
    for etape in config["stockage"]["etapes"]:
        dossier = RACINE / config["chemins"][etape] / dataset
        if dossier.exists():
            for f in dossier.rglob("*"):
                # On ignore les fichiers cachés (.DS_Store de macOS) et les téléchargements en cours.
                if f.is_file() and not f.name.startswith(".") and f.suffix not in (".part", ".tmp"):
                    fichiers[f.relative_to(data).as_posix()] = f.stat().st_size
    return fichiers


def fichiers_distants(fs, config: dict, dataset: str) -> dict[str, int]:
    """Fichiers du dataset sur SSP Cloud, sous la forme {chemin relatif à data/ : taille}."""
    racine = racine_distante(config, dataset)
    distants = {}
    for etape in config["stockage"]["etapes"]:
        dossier = f"{racine}/{etape}/{dataset}"
        if fs.exists(dossier):
            for chemin, info in fs.find(dossier, detail=True).items():
                distants[chemin.removeprefix(racine + "/")] = info["size"]
    return distants


def envoyer(config: dict, dataset: str, fs=None) -> int:
    """Copie vers SSP Cloud les fichiers du dataset absents ou modifiés. Renvoie le nombre copié."""
    fs = fs or connecter()
    racine = racine_distante(config, dataset)
    locaux, distants = fichiers_locaux(config, dataset), fichiers_distants(fs, config, dataset)
    a_copier = [f for f, taille in locaux.items() if distants.get(f) != taille]
    log.info("%s : %d fichier(s) locaux, %d déjà à jour sur SSP Cloud",
             dataset, len(locaux), len(locaux) - len(a_copier))

    t0 = time.time()
    for f in tqdm(a_copier, desc="Envoi", unit="fichier"):
        destination = f"{racine}/{f}"
        fs.makedirs(destination.rsplit("/", 1)[0], exist_ok=True)
        fs.put_file(str(RACINE / "data" / f), destination)
    log.info("%d fichier(s) envoyés vers s3://%s en %.0f s", len(a_copier), racine, time.time() - t0)
    return len(a_copier)


def recuperer(config: dict, dataset: str | None = None, fs=None) -> int:
    """Copie depuis SSP Cloud les fichiers absents ou modifiés en local (tous les datasets si
    dataset vaut None). Renvoie le nombre de fichiers copiés."""
    fs = fs or connecter()
    datasets = [dataset] if dataset else list(config["stockage"]["buckets"])
    total = 0
    for d in datasets:
        racine = racine_distante(config, d)
        locaux, distants = fichiers_locaux(config, d), fichiers_distants(fs, config, d)
        a_copier = [f for f, taille in distants.items() if locaux.get(f) != taille]
        log.info("%s : %d fichier(s) sur SSP Cloud, %d déjà à jour en local",
                 d, len(distants), len(distants) - len(a_copier))

        t0 = time.time()
        for f in tqdm(a_copier, desc=f"Récupération {d}", unit="fichier"):
            destination = RACINE / "data" / f
            destination.parent.mkdir(parents=True, exist_ok=True)
            fs.get_file(f"{racine}/{f}", str(destination))
        log.info("%d fichier(s) récupérés depuis s3://%s en %.0f s", len(a_copier), racine, time.time() - t0)
        total += len(a_copier)
    return total


if __name__ == "__main__":
    configurer_logs()
    parser = argparse.ArgumentParser(description="Synchronise data/ avec le stockage SSP Cloud.")
    parser.add_argument("action", choices=["envoyer", "recuperer"])
    parser.add_argument("--dataset", help="airparif, trafic… (obligatoire pour envoyer ; "
                                          "sans lui, recuperer prend tous les datasets)")
    args = parser.parse_args()
    config = charger_config()
    if args.action == "envoyer":
        if not args.dataset:
            parser.error("envoyer demande --dataset : on n'écrit que dans son propre espace")
        envoyer(config, args.dataset)
    else:
        recuperer(config, args.dataset)
