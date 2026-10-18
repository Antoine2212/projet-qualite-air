"""Extraction de la météo horaire depuis l'API Open-Meteo (archive historique).

Un fichier JSON brut par mois dans data/raw/meteo/, tel que renvoyé par l'API.
Lancement : uv run python -m src.extract.meteo
"""

import json
import logging
import time

import pandas as pd

from src.utils import charger_config, configurer_logs, dossier, ecrire_atomique, mois_de_la_periode, requete

log = logging.getLogger(__name__)


def telecharger_mois(config: dict, debut, fin) -> int:
    """Télécharge un mois et renvoie le nombre d'heures reçues (0 si déjà en cache)."""
    m = config["meteo"]
    fichier = dossier(config, "raw", "meteo") / f"meteo_{debut}_{fin}.json"
    if fichier.exists():
        log.info("%s déjà présent, ignoré", fichier.name)
        return 0

    params = {
        "latitude": m["latitude"],
        "longitude": m["longitude"],
        "start_date": debut.isoformat(),
        "end_date": fin.isoformat(),
        "hourly": ",".join(m["variables"]),
        "wind_speed_unit": m["wind_speed_unit"],
        "timezone": "UTC",
    }
    r = requete(m["url"], config, params)
    donnees = r.json()

    manquantes = set(m["variables"]) - set(donnees["hourly"])
    if manquantes:
        raise ValueError(f"Variables absentes de la réponse : {manquantes}")

    ecrire_atomique(fichier, r.content)
    n = len(donnees["hourly"]["time"])
    attendu = ((fin - debut).days + 1) * 24
    if n != attendu:
        log.warning("%s : %d heures reçues, %d attendues", fichier.name, n, attendu)
    log.info("%s : %d heures", fichier.name, n)
    return n


def extraire(config: dict) -> None:
    t0 = time.time()
    total = 0
    for debut, fin in mois_de_la_periode(config):
        n = telecharger_mois(config, debut, fin)
        total += n
        if n:
            time.sleep(config["api"]["pause_appels_s"])
    log.info("Météo terminée : %d nouvelles heures en %.0f s", total, time.time() - t0)


def charger_brut(config: dict) -> pd.DataFrame:
    """Relit tous les JSON bruts en une seule table (pour le notebook de contrôle)."""
    tables = []
    for fichier in sorted(dossier(config, "raw", "meteo").glob("meteo_*.json")):
        donnees = json.loads(fichier.read_text())
        tables.append(pd.DataFrame(donnees["hourly"]))
    return pd.concat(tables, ignore_index=True)


if __name__ == "__main__":
    configurer_logs()
    extraire(charger_config())
