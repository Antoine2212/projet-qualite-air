"""Extraction des mesures horaires des stations Airparif.

Le flux WFS d'Airparif (projet DIDON) ne garde que les dernières 24 h. L'historique
vient donc des fichiers horaires nationaux du LCSQA publiés sur data.gouv.fr
(un CSV par jour, toutes les stations de France, heures en UTC). On n'en garde
que les lignes dont l'organisme est Airparif, sans rien modifier d'autre.

- Mesures : data/raw/airparif/mesures_AAAA-MM-JJ.csv
- Stations (coordonnées, dates d'activité) : data/raw/airparif/stations_dataset_D.xls

Lancement : uv run python -m src.extract.airparif
"""

import logging
import time

import pandas as pd
import requests

from src.utils import charger_config, configurer_logs, dossier, ecrire_atomique, jours_de_la_periode, requete

log = logging.getLogger(__name__)

COLONNE_ORGANISME = 2  # 3e colonne du CSV : « Organisme »


def telecharger_stations(config: dict) -> None:
    """Télécharge le « Dataset D » du LCSQA : métadonnées de toutes les stations françaises."""
    fichier = dossier(config, "raw", "airparif") / "stations_dataset_D.xls"
    if fichier.exists():
        log.info("%s déjà présent, ignoré", fichier.name)
        return

    # L'adresse du fichier change à chaque mise à jour : on la lit dans la fiche du jeu.
    jeu = requete(config["airparif"]["url_dataset"], config).json()
    url = next(
        r["url"] for r in jeu["resources"]
        if r["title"].startswith("Dataset D") and r["format"] == "xls"
    )
    ecrire_atomique(fichier, requete(url, config).content)
    log.info("%s téléchargé depuis %s", fichier.name, url)


def telecharger_jour(config: dict, jour) -> int | None:
    """Télécharge un jour et renvoie le nombre de lignes Airparif.

    Renvoie 0 si le fichier est déjà en cache, None si le jour n'existe pas sur le serveur.
    """
    a = config["airparif"]
    fichier = dossier(config, "raw", "airparif") / f"mesures_{jour:%Y-%m-%d}.csv"
    if fichier.exists():
        return 0

    url = f"{a['url_mesures']}/{jour:%Y}/FR_E2_{jour:%Y-%m-%d}.csv"
    try:
        r = requete(url, config)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.warning("%s : fichier absent sur le serveur", jour)
            return None
        raise

    lignes = r.content.decode("utf-8-sig").splitlines()
    entete, mesures = lignes[0], lignes[1:]
    gardees = [l for l in mesures if l.split(";")[COLONNE_ORGANISME] == a["organisme"]]
    if not gardees:
        log.warning("%s : aucune ligne %s", jour, a["organisme"])
    ecrire_atomique(fichier, "\n".join([entete, *gardees]).encode("utf-8"))
    return len(gardees)


def extraire(config: dict) -> None:
    t0 = time.time()
    telecharger_stations(config)
    jours = jours_de_la_periode(config)
    total, absents = 0, []
    for i, jour in enumerate(jours, 1):
        n = telecharger_jour(config, jour)
        if n is None:
            absents.append(jour)
        elif n:
            total += n
            time.sleep(config["api"]["pause_appels_s"])
        if i % 30 == 0 or i == len(jours):
            log.info("%d/%d jours traités (%d lignes jusqu'ici)", i, len(jours), total)
    if absents:
        log.warning("%d jour(s) absent(s) du serveur : %s", len(absents), ", ".join(map(str, absents)))
    log.info("Airparif terminé : %d nouvelles lignes en %.0f s", total, time.time() - t0)


def charger_brut(config: dict) -> pd.DataFrame:
    """Relit tous les CSV bruts en une seule table, sans conversion de type."""
    fichiers = sorted(dossier(config, "raw", "airparif").glob("mesures_*.csv"))
    return pd.concat((pd.read_csv(f, sep=";", dtype=str) for f in fichiers), ignore_index=True)


def charger_stations(config: dict) -> pd.DataFrame:
    """Stations du Dataset D (toute la France : le filtre Airparif se fait au nettoyage)."""
    fichier = dossier(config, "raw", "airparif") / "stations_dataset_D.xls"
    return pd.read_excel(fichier, sheet_name="AirQualityStations")


if __name__ == "__main__":
    configurer_logs()
    extraire(charger_config())
