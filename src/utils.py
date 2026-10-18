"""Outils communs : configuration, journalisation, requêtes HTTP avec réessais, découpage de période."""

import logging
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
import yaml

RACINE = Path(__file__).resolve().parents[1]

log = logging.getLogger(__name__)


def charger_config(chemin: Path = RACINE / "config.yaml") -> dict:
    """Lit config.yaml et renvoie un dictionnaire."""
    with open(chemin, encoding="utf-8") as f:
        return yaml.safe_load(f)


def dossier(config: dict, etape: str, source: str) -> Path:
    """Renvoie (et crée) le dossier data/<etape>/<source>/, par exemple data/raw/meteo/."""
    chemin = RACINE / config["chemins"][etape] / source
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def configurer_logs() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s : %(message)s",
        datefmt="%H:%M:%S",
    )


def requete(url: str, config: dict, params: dict | None = None) -> requests.Response:
    """GET avec réessais : la pause double après chaque échec (2 s, 4 s, 8 s…).

    Les erreurs 4xx autres que 429 (trop de requêtes) ne sont pas réessayées :
    elles signalent une requête mal formée, qu'un nouvel essai ne corrigera pas.
    """
    api = config["api"]
    pause = api["pause_essai_s"]
    for essai in range(1, api["max_essais"] + 1):
        try:
            r = requests.get(url, params=params, timeout=api["timeout_s"])
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            code = getattr(e.response, "status_code", None)
            if code is not None and 400 <= code < 500 and code != 429:
                raise
            if essai == api["max_essais"]:
                raise
            log.warning("Essai %d/%d échoué (%s), nouvel essai dans %d s", essai, api["max_essais"], e, pause)
            time.sleep(pause)
            pause *= 2


def ecrire_atomique(chemin: Path, contenu: bytes) -> None:
    """Écrit d'abord un fichier temporaire, puis le renomme.

    Un téléchargement interrompu ne laisse donc jamais de fichier incomplet,
    que le cache prendrait ensuite pour un morceau valide.
    """
    tmp = chemin.with_suffix(chemin.suffix + ".part")
    tmp.write_bytes(contenu)
    tmp.replace(chemin)


def mois_de_la_periode(config: dict, freq: str = "MS") -> list[tuple[date, date]]:
    """Découpe la période en morceaux : liste de (premier jour, dernier jour), bornes incluses.

    freq="MS" donne des mois, freq="SMS" des demi-mois (du 1er au 14, du 15 à la fin).
    """
    debut = date.fromisoformat(config["periode"]["debut"])
    fin = date.fromisoformat(config["periode"]["fin"])
    morceaux = []
    bornes = pd.date_range(debut.replace(day=1), fin + timedelta(days=31), freq=freq)
    for d, suivant in zip(bornes[:-1], bornes[1:]):
        if suivant.date() <= debut:
            continue
        if d.date() > fin:
            break
        premier = max(d.date(), debut)
        dernier = min((suivant - pd.Timedelta(days=1)).date(), fin)
        morceaux.append((premier, dernier))
    return morceaux


def jours_de_la_periode(config: dict) -> list[date]:
    debut = date.fromisoformat(config["periode"]["debut"])
    fin = date.fromisoformat(config["periode"]["fin"])
    return [debut + timedelta(days=i) for i in range((fin - debut).days + 1)]
