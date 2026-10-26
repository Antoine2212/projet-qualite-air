"""Nettoyage du trafic routier de Paris (sortie : data/interim/).

Étapes, dans l'ordre de main() :
1. concaténer les fichiers mensuels bruts ;
2. passer de la convention « fin de période » à « début de période » ;
3. garder une seule version de chaque arc dans le référentiel (date_fin la plus récente) ;
4. retirer les arcs sans géométrie ;
5. mettre à NaN les longues séries de zéros (pannes) ;
6. garder les arcs qui ont un débit pour assez d'heures (seuil dans config.yaml) ;
7. compléter la grille : une ligne par arc et par heure, NaN si l'heure manque ;
8. ajouter à chaque ligne le libellé, la longueur et le centroïde de l'arc.

Sortie : un seul fichier, data/interim/trafic.parquet.

Usage : uv run python -m src.clean.trafic
"""
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from src.extract.trafic import RACINE, lire_config

logger = logging.getLogger(__name__)


def charger_brut(dossier: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Concatène les fichiers mensuels du trafic et lit le référentiel."""
    fichiers = sorted(dossier.glob("trafic_*.parquet"))
    trafic = pd.concat([pd.read_parquet(f) for f in fichiers], ignore_index=True)
    ref = pd.read_parquet(dossier / "referentiel.parquet")
    logger.info("%d fichiers mensuels, %d lignes de trafic", len(fichiers), len(trafic))
    return trafic, ref


def preparer(trafic: pd.DataFrame) -> pd.DataFrame:
    """Garde iu_ac, q et k, et remplace t_1h (fin de période) par heure (début de période).

    etat_trafic est déduit de k et etat_barre = Invalide correspond toujours à q et k
    manquants : ces deux colonnes n'apportent rien de plus.
    """
    return pd.DataFrame({
        "iu_ac": trafic["iu_ac"],
        "heure": trafic["t_1h"] - pd.Timedelta(hours=1),
        "q": trafic["q"],
        "k": trafic["k"],
    })


def dedoublonner_referentiel(ref: pd.DataFrame) -> gpd.GeoDataFrame:
    """Garde une version par arc (date_fin puis date_debut la plus récente), en Lambert-93."""
    ref = ref.sort_values(["iu_ac", "date_fin", "date_debut"], kind="stable")
    unique = ref.drop_duplicates("iu_ac", keep="last")
    logger.info("référentiel : %d lignes initialement, %d versions anciennes retirées", len(ref), len(ref) - len(unique))
    colonnes = ["iu_ac", "libelle", "libelle_nd_amont", "libelle_nd_aval"]
    geometrie = gpd.GeoSeries.from_wkb(unique["geo_shape"], crs=4326).to_crs(2154)
    return gpd.GeoDataFrame(unique[colonnes], geometry=geometrie)


def retirer_arcs_sans_geo(trafic: pd.DataFrame, arcs: gpd.GeoDataFrame) -> pd.DataFrame:
    """Retire les arcs du trafic absents du référentiel (pas de position connue)."""
    garde = trafic["iu_ac"].isin(arcs["iu_ac"])
    logger.info("arcs sans géométrie : %d arcs, %d lignes retirées",
                trafic.loc[~garde, "iu_ac"].nunique(), (~garde).sum())
    return trafic[garde]


def toutes_les_heures(trafic: pd.DataFrame) -> pd.DatetimeIndex:
    """Toutes les heures entre la première et la dernière heure du trafic."""
    return pd.date_range(trafic["heure"].min(), trafic["heure"].max(), freq="h")


def part_heures_sans_debit(trafic: pd.DataFrame) -> pd.Series:
    """Part des heures de la période sans débit, pour chaque arc.

    Une heure absente du fichier compte comme une heure sans débit.
    """
    n_heures = len(toutes_les_heures(trafic))
    return 1 - trafic.groupby("iu_ac")["q"].count() / n_heures


def garder_arcs_mesures(trafic: pd.DataFrame, part_max: float) -> pd.DataFrame:
    """Garde les arcs dont la part d'heures sans débit est inférieure à `part_max`."""
    part = part_heures_sans_debit(trafic)
    gardes = part.index[part <= part_max]
    logger.info("arcs avec plus de %.0f %% d'heures sans débit : %d retirés, %d gardés",
                part_max * 100, len(part) - len(gardes), len(gardes))
    return trafic[trafic["iu_ac"].isin(gardes)]


def longueur_series_de_zeros(trafic: pd.DataFrame, colonne: str) -> pd.Series:
    """Pour chaque ligne à zéro, longueur (en lignes) de la série de zéros qui la contient ; 0 sinon.

    Les séries se suivent ligne à ligne pour un même arc : une valeur manquante coupe la série.
    """
    trie = trafic.sort_values(["iu_ac", "heure"])
    zero = trie[colonne] == 0
    # une nouvelle série commence quand on passe de zéro à non zéro (ou l'inverse) ou qu'on change d'arc
    debut_serie = (zero != zero.shift()) | (trie["iu_ac"] != trie["iu_ac"].shift())
    return zero.groupby(debut_serie.cumsum()).transform("sum") # le .transform diffuse la valeur de la "sum" sur chaque ligne du groupe


def retirer_longues_series_de_zeros(trafic: pd.DataFrame, colonne: str, seuil: int) -> pd.DataFrame:
    """Met à NaN les séries de plus de `seuil` heures consécutives à zéro (capteur en panne)."""
    panne = longueur_series_de_zeros(trafic, colonne) > seuil
    lignes = panne.index[panne]
    logger.info("%s : %d valeurs nulles dans des séries de plus de %d h mises à NaN (%d arcs)",
                colonne, len(lignes), seuil, trafic.loc[lignes, "iu_ac"].nunique())
    trafic = trafic.copy()
    trafic.loc[lignes, colonne] = np.nan
    return trafic


def completer_grille(trafic: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par arc et par heure ; les heures absentes sont ajoutées avec q et k à NaN."""
    grille = pd.MultiIndex.from_product([sorted(trafic["iu_ac"].unique()), toutes_les_heures(trafic)],
                                        names=["iu_ac", "heure"])
    # from_product fait un produit cartésien 
    complet = trafic.set_index(["iu_ac", "heure"]).reindex(grille).reset_index()
    # reindex crée des lignes avec NaN partout pour les index (couple (axe, heure))
    # reset index retransforme (axe, heure) en colonnes classiques 
    logger.info("grille complète : %d lignes, dont %d ajoutées", len(complet), len(complet) - len(trafic))
    return complet


def ajouter_infos_arcs(trafic: pd.DataFrame, arcs: gpd.GeoDataFrame) -> pd.DataFrame:
    """Ajoute à chaque ligne le libellé, la longueur et le centroïde de son arc.

    Longueur et centroïde sont en mètres, en Lambert-93 (EPSG:2154).
    """
    infos = pd.DataFrame({
        "iu_ac": arcs["iu_ac"],
        "libelle": arcs["libelle"],
        "longueur_m": arcs.length,
        "x_centroide": arcs.centroid.x,
        "y_centroide": arcs.centroid.y,
    })
    # validate : chaque arc n'a qu'une ligne dans infos, la fusion ne duplique donc aucune ligne
    return trafic.merge(infos, on="iu_ac", how="left", validate="many_to_one")


def main() -> None:
    """Nettoie le trafic et écrit le résultat dans data/interim/trafic.parquet."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = lire_config()
    cfg_t = cfg["trafic"]
    sortie = RACINE / cfg["chemins"]["interim"]
    sortie.mkdir(parents=True, exist_ok=True)

    trafic, ref = charger_brut(RACINE / cfg["chemins"]["raw"] / "trafic")
    trafic = preparer(trafic)
    arcs = dedoublonner_referentiel(ref)
    trafic = retirer_arcs_sans_geo(trafic, arcs)
    for colonne in ["q", "k"]:
        trafic = retirer_longues_series_de_zeros(trafic, colonne, cfg_t["zeros_consecutifs_max"])
    trafic = garder_arcs_mesures(trafic, cfg_t["part_sans_debit_max"])
    trafic = completer_grille(trafic)
    trafic = ajouter_infos_arcs(trafic, arcs)

    trafic.to_parquet(sortie / "trafic.parquet", index=False)
    logger.info("écrit dans %s : %d lignes, colonnes %s", sortie / "trafic.parquet", len(trafic), list(trafic.columns))


if __name__ == "__main__":
    main()
