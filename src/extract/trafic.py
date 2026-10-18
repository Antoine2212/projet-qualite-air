"""Extraction des comptages routiers de Paris (API Opendatasoft du portail Open Data).

- Référentiel des arcs (iu_ac, libellé, géométrie) : endpoint /records, lu page par page.
- Comptages horaires : endpoint /exports/parquet, un fichier par demi-mois
  (un mois entier prend près de 5 minutes côté serveur, trop proche du délai maximal).
  L'export n'a pas de limite de lignes, contrairement à /records (10 000 au plus).

Les heures sont demandées en UTC (timezone=UTC). L'horodatage t_1h marque
la fin de la période de comptage : le décalage se fera au nettoyage.

Lancement : uv run python -m src.extract.trafic
"""

import json
import logging
import time
from datetime import timedelta

import pandas as pd

from src.utils import charger_config, configurer_logs, dossier, ecrire_atomique, mois_de_la_periode, requete

log = logging.getLogger(__name__)


def telecharger_referentiel(config: dict) -> None:
    t = config["trafic"]
    fichier = dossier(config, "raw", "trafic") / "referentiel_arcs.json"
    if fichier.exists():
        log.info("%s déjà présent, ignoré", fichier.name)
        return

    url = f"{t['url_base']}/{t['dataset_referentiel']}/records"
    resultats, offset, total = [], 0, None
    while total is None or offset < total:
        r = requete(url, config, {"limit": t["taille_page"], "offset": offset})
        page = r.json()
        total = page["total_count"]
        resultats.extend(page["results"])
        offset += t["taille_page"]
        time.sleep(config["api"]["pause_appels_s"])

    if len(resultats) != total:
        log.warning("Référentiel : %d arcs reçus, %d annoncés", len(resultats), total)
    ecrire_atomique(fichier, json.dumps(resultats, ensure_ascii=False).encode())
    log.info("%s : %d arcs", fichier.name, len(resultats))


def telecharger_mois(config: dict, debut, fin) -> int:
    """Télécharge un demi-mois de comptages et renvoie le nombre de lignes (0 si déjà en cache)."""
    t = config["trafic"]
    fichier = dossier(config, "raw", "trafic") / f"comptages_{debut}_{fin}.parquet"
    if fichier.exists():
        log.info("%s déjà présent, ignoré", fichier.name)
        return 0

    # Borne de fin exclue : on demande jusqu'au lendemain du dernier jour, 00:00.
    lendemain = fin + timedelta(days=1)
    params = {
        "select": ",".join(t["colonnes"]),
        "where": f"t_1h >= date'{debut.isoformat()}' and t_1h < date'{lendemain.isoformat()}'",
        "timezone": "UTC",
    }
    t0 = time.time()
    r = requete(f"{t['url_base']}/{t['dataset_comptages']}/exports/parquet", config, params)
    ecrire_atomique(fichier, r.content)

    n = len(pd.read_parquet(fichier, columns=["iu_ac"]))
    if n == 0:
        log.warning("%s : aucune ligne, la période est-elle couverte par l'API ?", fichier.name)
    log.info("%s : %d lignes, %.1f Mo, %.0f s", fichier.name, n, len(r.content) / 1e6, time.time() - t0)
    return n


def extraire(config: dict) -> None:
    t0 = time.time()
    telecharger_referentiel(config)
    total = 0
    for debut, fin in mois_de_la_periode(config, freq="SMS"):
        n = telecharger_mois(config, debut, fin)
        total += n
        if n:
            time.sleep(config["api"]["pause_appels_s"])
    log.info("Trafic terminé : %d nouvelles lignes en %.0f s", total, time.time() - t0)


def charger_referentiel(config: dict) -> pd.DataFrame:
    fichier = dossier(config, "raw", "trafic") / "referentiel_arcs.json"
    return pd.json_normalize(json.loads(fichier.read_text()))


def charger_brut(config: dict) -> pd.DataFrame:
    """Relit tous les mois de comptages en une seule table (pour le notebook de contrôle)."""
    fichiers = sorted(dossier(config, "raw", "trafic").glob("comptages_*.parquet"))
    return pd.concat((pd.read_parquet(f) for f in fichiers), ignore_index=True)


if __name__ == "__main__":
    configurer_logs()
    extraire(charger_config())
