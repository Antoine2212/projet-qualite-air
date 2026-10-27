"""Synchronisation du dossier data/ avec le stockage S3 de SSP Cloud (MinIO).

Le code vit sur GitHub, les données sur SSP Cloud :
- envoyer   : copie data/<étape>/ vers s3://<bucket>/<dossier>/<étape>/
- recuperer : copie dans l'autre sens, pour qui n'a pas relancé l'extraction

Seuls les fichiers absents ou de taille différente sont copiés : on peut relancer sans risque.

Identifiants : jamais dans le code ni dans Git. Ils viennent des variables d'environnement
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN et AWS_S3_ENDPOINT,
injectées automatiquement dans les services SSP Cloud. Sur un autre ordinateur, les copier
depuis https://datalab.sspcloud.fr/account/storage dans un fichier .env (voir .env.example).
Ils expirent au bout de 7 jours.

Lancement :
  uv run python -m src.stockage envoyer
  uv run python -m src.stockage recuperer
"""

import argparse
import logging
import os
import time
from pathlib import Path

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
            "service SSP Cloud, ou copie-les depuis https://datalab.sspcloud.fr/account/storage "
            "dans un fichier .env à la racine du projet."
        )
    # s3fs lit lui-même les clés dans l'environnement ; il ne lui manque que l'adresse du serveur.
    return s3fs.S3FileSystem(client_kwargs={"endpoint_url": f"https://{os.environ['AWS_S3_ENDPOINT']}"})


def racine_distante(config: dict) -> str:
    s = config["stockage"]
    if not s["bucket"]:
        raise ValueError("Renseigne stockage.bucket (ton identifiant SSP Cloud) dans config.yaml")
    return f"{s['bucket']}/{s['dossier']}"


def fichiers_locaux(config: dict) -> dict[str, int]:
    """Fichiers de data/ à synchroniser, sous la forme {chemin relatif à data/ : taille}."""
    data = RACINE / "data"
    fichiers = {}
    for etape in config["stockage"]["etapes"]:
        dossier = RACINE / config["chemins"][etape]
        if dossier.exists():
            for f in dossier.rglob("*"):
                # On ignore les fichiers cachés (.DS_Store de macOS) et les téléchargements en cours.
                if f.is_file() and not f.name.startswith(".") and not f.name.endswith(".part"):
                    fichiers[f.relative_to(data).as_posix()] = f.stat().st_size
    return fichiers


def fichiers_distants(fs, config: dict) -> dict[str, int]:
    racine = racine_distante(config)
    if not fs.exists(racine):
        return {}
    distants = {}
    for chemin, info in fs.find(racine, detail=True).items():
        relatif = chemin.removeprefix(racine + "/")
        if relatif.split("/")[0] in config["stockage"]["etapes"]:
            distants[relatif] = info["size"]
    return distants


def envoyer(config: dict, fs=None) -> int:
    """Copie vers SSP Cloud les fichiers absents ou modifiés. Renvoie le nombre de fichiers copiés."""
    fs = fs or connecter()
    racine = racine_distante(config)
    locaux, distants = fichiers_locaux(config), fichiers_distants(fs, config)
    a_copier = [f for f, taille in locaux.items() if distants.get(f) != taille]
    log.info("%d fichier(s) locaux, %d déjà à jour sur SSP Cloud", len(locaux), len(locaux) - len(a_copier))

    t0 = time.time()
    for f in tqdm(a_copier, desc="Envoi", unit="fichier"):
        destination = f"{racine}/{f}"
        fs.makedirs(destination.rsplit("/", 1)[0], exist_ok=True)
        fs.put_file(str(RACINE / "data" / f), destination)
    log.info("%d fichier(s) envoyés vers s3://%s en %.0f s", len(a_copier), racine, time.time() - t0)
    return len(a_copier)


def recuperer(config: dict, fs=None) -> int:
    """Copie depuis SSP Cloud les fichiers absents ou modifiés en local. Renvoie le nombre copié."""
    fs = fs or connecter()
    racine = racine_distante(config)
    locaux, distants = fichiers_locaux(config), fichiers_distants(fs, config)
    a_copier = [f for f, taille in distants.items() if locaux.get(f) != taille]
    log.info("%d fichier(s) sur SSP Cloud, %d déjà à jour en local", len(distants), len(distants) - len(a_copier))

    t0 = time.time()
    for f in tqdm(a_copier, desc="Récupération", unit="fichier"):
        destination = RACINE / "data" / f
        destination.parent.mkdir(parents=True, exist_ok=True)
        fs.get_file(f"{racine}/{f}", str(destination))
    log.info("%d fichier(s) récupérés depuis s3://%s en %.0f s", len(a_copier), racine, time.time() - t0)
    return len(a_copier)


if __name__ == "__main__":
    configurer_logs()
    parser = argparse.ArgumentParser(description="Synchronise data/ avec le stockage SSP Cloud.")
    parser.add_argument("action", choices=["envoyer", "recuperer"])
    args = parser.parse_args()
    config = charger_config()
    {"envoyer": envoyer, "recuperer": recuperer}[args.action](config)
