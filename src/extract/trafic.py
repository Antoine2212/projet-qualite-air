"""Extraction du trafic routier de Paris (API Opendatasoft, comptages permanents).

Le jeu ne garde que 13 mois glissants. Un mois = environ 2 millions de lignes,
trop pour l'endpoint `records` (offset + limit <= 10 000) : on utilise l'endpoint
`exports`, un fichier Parquet par mois, sauvegardé brut dans data/raw/trafic/.

Attention : `t_1h` est en UTC et marque la FIN de la période d'une heure. Le
fichier d'un mois contient donc t_1h du 1er à 01:00 au 1er du mois suivant à
00:00 inclus, soit exactement les heures qui commencent dans le mois. Le
décalage d'une heure (début de période) se fait au nettoyage.

Usage en script : uv run python -m src.extract.trafic [AAAA-MM]
Usage en notebook : from src.extract.trafic import main ; main()
"""
import logging
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import requests
import yaml

logger = logging.getLogger(__name__)

# Racine du dépôt (ce fichier est dans src/extract/) : les chemins ne dépendent
# plus du dossier depuis lequel on lance le script ou le notebook.
RACINE = Path(__file__).resolve().parents[2]

# La config est un dictionnaire imbriqué : cfg["trafic"]["dataset"], etc.
Config = dict[str, Any]


def lire_config(chemin: Path = RACINE / "config.yaml") -> Config:
    """Lit config.yaml et renvoie son contenu sous forme de dictionnaire."""
    with open(chemin, encoding="utf-8") as f:
        return yaml.safe_load(f)


def liste_mois(debut: str, fin: str) -> list[pd.Timestamp]:
    """Liste des débuts de mois entre deux dates AAAA-MM-JJ (mois de `fin` inclus)."""
    return list(pd.date_range(pd.Timestamp(debut).replace(day=1), pd.Timestamp(fin), freq="MS"))


def telecharger(url: str, params: dict[str, str], sortie: Path, cfg_t: Config) -> None:
    """Télécharge `url` vers `sortie` avec réessais (pause doublée à chaque échec).

    `cfg_t` est la section `trafic` de la config (timeouts, tentatives, pauses).
    Le fichier est écrit sous un nom temporaire puis renommé : un téléchargement
    interrompu n'est jamais pris pour une extraction complète par le cache.
    """
    tmp = sortie.with_suffix(".tmp")
    for essai in range(cfg_t["tentatives"]):
        try:
            with requests.get(
                url,
                params=params,
                stream=True,
                timeout=(cfg_t["timeout_connexion"], cfg_t["timeout_lecture"]),
            ) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for morceau in r.iter_content(chunk_size=1 << 20):
                        f.write(morceau)
            tmp.rename(sortie)
            return
        except requests.RequestException as e:
            pause = cfg_t["pause_retry"] * 2**essai
            logger.warning("échec (essai %d/%d) : %s ; nouvel essai dans %d s",
                           essai + 1, cfg_t["tentatives"], e, pause)
            time.sleep(pause)
    raise RuntimeError(f"téléchargement impossible : {url}")


def get_trafic_mois(cfg: Config, mois: pd.Timestamp, dossier: Path) -> Path:
    """Télécharge le trafic d'un mois (début de mois en UTC) ; ne fait rien si déjà présent."""
    sortie = dossier / f"trafic_{mois:%Y-%m}.parquet"
    if sortie.exists():
        logger.info("%s déjà présent, ignoré", sortie.name)
        return sortie

    cfg_t = cfg["trafic"]
    suivant = mois + pd.offsets.MonthBegin(1)
    # t_1h marque la fin de l'heure : l'heure de 00:00 à 01:00 le 1er du mois a t_1h = 01:00,
    # d'où « > » au début, et la dernière heure du mois (23:00 à 00:00) a t_1h = 1er du mois
    # suivant à 00:00, d'où « <= » à la fin.
    # L'heure doit être écrite en entier : avec date'AAAA-MM-JJ' seul, l'API compare au jour
    # près (« <= date'2026-10-01' » garderait toute la journée du 1er octobre).
    params = {
        "select": ",".join(cfg_t["colonnes"]),
        "where": f"t_1h > date'{mois:%Y-%m-%d}T00:00:00Z' and t_1h <= date'{suivant:%Y-%m-%d}T00:00:00Z'",
    }
    url = f"{cfg_t['url_base']}/{cfg_t['dataset']}/exports/parquet"

    debut = time.time()
    logger.info("téléchargement du trafic %s", f"{mois:%Y-%m}")
    telecharger(url, params, sortie, cfg_t)
    n = pq.read_metadata(sortie).num_rows
    if n == 0:
        logger.warning("%s : aucune ligne reçue (mois hors de l'historique de l'API ?)", sortie.name)
    logger.info("%s : %d lignes en %.0f s", sortie.name, n, time.time() - debut)
    return sortie


def get_referentiel(cfg: Config, dossier: Path) -> Path:
    """Télécharge le référentiel géographique des arcs ; ne fait rien si déjà présent."""
    sortie = dossier / "referentiel.parquet"
    if sortie.exists():
        logger.info("%s déjà présent, ignoré", sortie.name)
        return sortie

    cfg_t = cfg["trafic"]
    url = f"{cfg_t['url_base']}/{cfg_t['dataset_referentiel']}/exports/parquet"
    telecharger(url, {}, sortie, cfg_t)
    logger.info("%s : %d lignes", sortie.name, pq.read_metadata(sortie).num_rows)
    return sortie


def main(mois_unique: str | None = None) -> None:
    """Télécharge le référentiel puis le trafic de la période (ou d'un seul mois AAAA-MM)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = lire_config()
    dossier = RACINE / cfg["chemins"]["raw"] / "trafic"
    dossier.mkdir(parents=True, exist_ok=True)

    if mois_unique:
        liste = [pd.Timestamp(mois_unique + "-01")]
    else:
        liste = liste_mois(cfg["periode"]["debut"], cfg["periode"]["fin"])

    get_referentiel(cfg, dossier)
    for mois in liste:
        time.sleep(cfg["trafic"]["pause_entre_appels"])
        get_trafic_mois(cfg, mois, dossier)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
