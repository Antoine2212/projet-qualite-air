"""Nettoyage des mesures horaires Airparif (fichiers LCSQA bruts de data/raw/airparif/).

Règle d'or : on ne bouche aucun trou ici. Une valeur fausse devient NaN ;
l'imputation viendra plus tard, sur l'échantillon d'entraînement seulement.

Sorties dans data/interim/airparif/ :
- mesures.parquet : une ligne par (station, heure UTC), une colonne par polluant,
  sur une grille horaire complète (les heures absentes sont visibles en NaN).
- stations.parquet : code, nom, type (trafic / fond), implantation, coordonnées, polluants mesurés.
- anomalies.parquet : valeurs écartées ou suspectes (capteur figé, pic isolé), pour le rapport.
- couverture.parquet : pour chaque série (station × polluant), part des heures avec une valeur,
  première et dernière mesure, nombre de trous courts et longs.
- trous.parquet : chaque trou (heures manquantes d'affilée) avec sa durée, court ou long.
- decisions.csv : chaque décision de nettoyage avec le nombre de lignes concernées.

Lancement : uv run python -m src.clean.airparif
"""

import logging

import pandas as pd

from src.extract import airparif as extraction
from src.utils import charger_config, configurer_logs, dossier

log = logging.getLogger(__name__)

COLONNES = {
    "Date de début": "debut",
    "Date de fin": "fin",
    "code site": "station",
    "nom site": "nom",
    "type d'implantation": "implantation",
    "type d'influence": "influence",
    "Polluant": "polluant",
    "valeur": "valeur",
    "unité de mesure": "unite",
    "code qualité": "code_qualite",
    "validité": "validite",
}

# Codes de validité du rapportage européen (vocabulaire « observationvalidity ») :
# 1 = valide, 2 et 3 = valide sous la limite de détection / de quantification,
# 4 = valide (ozone, méthode CCQM.O3.2019), -1 et -99 = invalide.
VALIDITES_OK = {"1", "2", "3", "4"}


TABLES = ("mesures", "stations", "anomalies", "couverture", "trous")


class Journal:
    """Tableau des décisions de nettoyage, à reprendre tel quel dans le rapport."""

    def __init__(self):
        self.lignes = []

    def noter(self, etape: str, concernees: int, restantes: int, decision: str) -> None:
        self.lignes.append(
            {"etape": etape, "lignes_concernees": concernees, "lignes_restantes": restantes, "decision": decision}
        )
        log.info("%s : %d ligne(s) concernée(s) → %s", etape, concernees, decision)

    def table(self) -> pd.DataFrame:
        return pd.DataFrame(self.lignes)


def preparer(brut: pd.DataFrame, config: dict, journal: Journal) -> pd.DataFrame:
    """Renomme, filtre les polluants et stations, convertit les types."""
    a = config["airparif"]
    df = brut[list(COLONNES)].rename(columns=COLONNES)
    journal.noter("Lecture des fichiers bruts", len(df), len(df), "lignes Airparif de la période")

    hors_polluants = ~df["polluant"].isin(list(a["polluants"]))
    journal.noter(
        "Polluants hors étude",
        int(hors_polluants.sum()),
        int((~hors_polluants).sum()),
        f"supprimées ({', '.join(sorted(df.loc[hors_polluants, 'polluant'].unique()))})",
    )
    df = df[~hors_polluants]

    if a["stations"]:
        hors_stations = ~df["station"].isin(a["stations"])
        journal.noter("Stations hors liste", int(hors_stations.sum()), int((~hors_stations).sum()), "supprimées")
        df = df[~hors_stations]

    unites = df["unite"].unique()
    if set(unites) != {"µg-m3"}:
        raise ValueError(f"Unités inattendues : {unites}")

    # Les fichiers LCSQA sont en UTC ; l'heure retenue est le début de la période.
    df = df.assign(
        debut=pd.to_datetime(df["debut"], format="%Y/%m/%d %H:%M:%S", utc=True),
        fin=pd.to_datetime(df["fin"], format="%Y/%m/%d %H:%M:%S", utc=True),
        # Une virgule décimale ou un texte parasite (« n/d ») deviendrait NaN ici : on les compte.
        valeur_num=pd.to_numeric(df["valeur"].str.replace(",", ".", regex=False), errors="coerce"),
    )
    parasites = df["valeur"].notna() & df["valeur_num"].isna()
    journal.noter("Valeurs non numériques", int(parasites.sum()), len(df), "mises à NaN")
    df = df.drop(columns="valeur").rename(columns={"valeur_num": "valeur"})

    pas_horaire = (df["fin"] - df["debut"]) != pd.Timedelta(hours=1)
    if pas_horaire.any():
        raise ValueError(f"{pas_horaire.sum()} ligne(s) ne couvrent pas exactement une heure")
    return df.drop(columns=["fin", "unite"])


def dedoublonner(df: pd.DataFrame, journal: Journal) -> pd.DataFrame:
    """Doublons exacts, puis doublons (station, polluant, heure) : on garde la mesure validée."""
    n = len(df)
    df = df.drop_duplicates()
    journal.noter("Doublons exacts", n - len(df), len(df), "supprimés")

    n = len(df)
    rang_qualite = df["code_qualite"].map({"A": 0, "R": 1, "N": 2}).fillna(3)
    df = (
        df.assign(_rang=rang_qualite)
        .sort_values(["station", "polluant", "debut", "_rang"])
        .drop_duplicates(["station", "polluant", "debut"], keep="first")
        .drop(columns="_rang")
    )
    journal.noter(
        "Doublons (station, polluant, heure)", n - len(df), len(df),
        "gardée : la mesure au meilleur code qualité (A validé > R non validé > N invalide)",
    )
    return df


def marquer_invalides(df: pd.DataFrame, config: dict, journal: Journal) -> pd.DataFrame:
    """Met à NaN les valeurs invalidées par Airparif et les valeurs physiquement impossibles."""
    zero_ok = set(config["airparif"]["nettoyage"]["zero_plausible"])
    valeur = df["valeur"].copy()

    invalide = ~df["validite"].isin(VALIDITES_OK)
    journal.noter(
        "Invalidée par Airparif (validité -1)", int(invalide.sum()), len(df),
        "mise à NaN (la valeur est en général déjà vide dans le fichier)",
    )
    valeur[invalide] = float("nan")

    negative = valeur < 0
    journal.noter(
        "Valeur négative", int(negative.sum()), len(df),
        "mise à NaN, comme le demande la consigne : ce sont de petits écarts de l'appareil "
        "autour de zéro, donc des trous qui ne touchent que les heures très peu polluées (MNAR)",
    )
    valeur[negative] = float("nan")

    nulle = (valeur == 0) & ~df["polluant"].isin(zero_ok)
    journal.noter(
        "Valeur nulle", int(nulle.sum()), len(df),
        f"mise à NaN, sauf pour {', '.join(sorted(zero_ok))} où 0 est plausible",
    )
    valeur[nulle] = float("nan")

    non_validee = (df["code_qualite"] == "R") & valeur.notna()
    journal.noter(
        "Mesure non encore validée (code R)", int(non_validee.sum()), len(df),
        "gardée : valeur temps réel, pas encore relue par Airparif",
    )
    return df.assign(valeur=valeur)


def reperer_anomalies(df: pd.DataFrame, config: dict, journal: Journal) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Capteur figé (mis à NaN) et pics isolés (gardés mais signalés).

    Le calcul se fait série par série (station × polluant), sur une grille horaire
    complète : deux heures séparées par un trou ne sont jamais considérées comme voisines.
    """
    n = config["airparif"]["nettoyage"]
    df = df.sort_values(["station", "polluant", "debut"]).reset_index(drop=True)
    serie = df.groupby(["station", "polluant"], sort=False)

    # Heure précédente de la même série, et égalité stricte de la valeur.
    contigu = serie["debut"].diff() == pd.Timedelta(hours=1)
    meme_valeur = (serie["valeur"].diff() == 0) & contigu
    # Numéro de « plateau » : change à chaque fois que la valeur change ou qu'un trou apparaît.
    plateau = (~meme_valeur).cumsum()
    longueur = df.groupby(plateau)["valeur"].transform("size")
    figee = (longueur >= n["heures_figees_min"]) & (df["valeur"] >= n["figee_plancher_ugm3"])

    # Pic isolé : très au-dessus de la médiane des 24 heures qui l'entourent.
    mediane = serie["valeur"].transform(lambda s: s.rolling(25, center=True, min_periods=12).median())
    pic = (df["valeur"] > n["pic_facteur"] * mediane) & (df["valeur"] > n["pic_plancher_ugm3"])

    anomalies = pd.concat([
        df.loc[figee, ["station", "polluant", "debut", "valeur"]].assign(type="capteur figé", action="mise à NaN"),
        df.loc[pic, ["station", "polluant", "debut", "valeur"]].assign(type="pic isolé", action="gardée"),
    ], ignore_index=True)

    journal.noter(
        "Capteur figé", int(figee.sum()), len(df),
        f"mise à NaN (même valeur ≥ {n['figee_plancher_ugm3']} µg/m³ pendant au moins {n['heures_figees_min']} h d'affilée)",
    )
    journal.noter(
        "Pic isolé", int(pic.sum()), len(df),
        f"gardée mais signalée (> {n['pic_facteur']} × médiane sur 24 h et > {n['pic_plancher_ugm3']} µg/m³)",
    )
    df.loc[figee, "valeur"] = float("nan")
    # Mêmes noms de polluants que dans les autres tables (no2, pm25…).
    anomalies["polluant"] = anomalies["polluant"].map(config["airparif"]["polluants"])
    anomalies = anomalies.rename(columns={"debut": "heure"})
    return df, anomalies


def passer_en_large(df: pd.DataFrame, config: dict, journal: Journal) -> pd.DataFrame:
    """Une ligne par (station, heure), une colonne par polluant, sur une grille horaire complète."""
    noms = config["airparif"]["polluants"]
    large = (
        df.pivot(index=["station", "debut"], columns="polluant", values="valeur")
        .rename(columns=noms)
        .reindex(columns=list(noms.values()))
    )

    p = config["periode"]
    heures = pd.date_range(p["debut"], pd.Timestamp(p["fin"]) + pd.Timedelta(hours=23), freq="h", tz="UTC")
    grille = pd.MultiIndex.from_product([sorted(df["station"].unique()), heures], names=["station", "heure"])
    n_avant = len(large)
    large = large.rename_axis(index={"debut": "heure"}).reindex(grille)
    journal.noter(
        "Grille horaire complète", len(large) - n_avant, len(large),
        "heures absentes ajoutées en NaN (une ligne par station et par heure)",
    )
    large.columns.name = None
    return large.reset_index()


def decrire_trous(mesures: pd.DataFrame, config: dict, journal: Journal) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Liste les trous de chaque série et résume sa couverture.

    Une série n'est décrite que si la station mesure ce polluant au moins une fois :
    un polluant jamais mesuré n'est pas un trou, c'est une absence d'appareil.
    """
    n = config["airparif"]["nettoyage"]
    polluants = list(config["airparif"]["polluants"].values())
    long_ = mesures.melt(id_vars=["station", "heure"], value_vars=polluants, var_name="polluant", value_name="valeur")
    mesurees = long_.groupby(["station", "polluant"])["valeur"].transform("count") > 0
    long_ = long_[mesurees].sort_values(["station", "polluant", "heure"]).reset_index(drop=True)

    # Numéro de bloc : change à chaque passage valeur ↔ NaN, à l'intérieur d'une série.
    manque = long_["valeur"].isna()
    serie = long_["station"] + "|" + long_["polluant"]
    bloc = ((manque != manque.shift()) | (serie != serie.shift())).cumsum()
    trous = (
        long_[manque]
        .groupby(bloc[manque])
        .agg(station=("station", "first"), polluant=("polluant", "first"),
             debut=("heure", "first"), fin=("heure", "last"), duree_h=("heure", "size"))
        .reset_index(drop=True)
    )
    trous["type"] = trous["duree_h"].le(n["trou_court_max_h"]).map({True: "court", False: "long"})

    valeurs = long_.dropna(subset=["valeur"]).groupby(["station", "polluant"])["heure"]
    couverture = pd.DataFrame({
        "heures_valides": long_.groupby(["station", "polluant"])["valeur"].count(),
        "part_valide": long_.groupby(["station", "polluant"])["valeur"].apply(lambda v: v.notna().mean()).round(3),
        "premiere_mesure": valeurs.min(),
        "derniere_mesure": valeurs.max(),
    })
    nb = trous.groupby(["station", "polluant", "type"]).size().unstack(fill_value=0)
    couverture["trous_courts"] = nb.get("court", 0)
    couverture["trous_longs"] = nb.get("long", 0)
    couverture["trou_max_h"] = trous.groupby(["station", "polluant"])["duree_h"].max()
    couverture = couverture.fillna({"trous_courts": 0, "trous_longs": 0, "trou_max_h": 0}).astype(
        {"trous_courts": int, "trous_longs": int, "trou_max_h": int}
    )
    couverture["faible_couverture"] = couverture["part_valide"] < n["couverture_min"]
    couverture = couverture.reset_index()

    faibles = couverture[couverture["faible_couverture"]]
    journal.noter(
        "Série à faible couverture", len(faibles), len(couverture),
        f"signalée, pas supprimée (< {n['couverture_min']:.0%} des heures) : "
        + ", ".join(faibles["station"] + " " + faibles["polluant"]),
    )
    journal.noter(
        "Trous courts / longs", len(trous), len(trous),
        f"{(trous['type'] == 'court').sum()} trous de {n['trou_court_max_h']} h ou moins, "
        f"{(trous['type'] == 'long').sum()} pannes plus longues : aucun n'est bouché ici",
    )
    return couverture, trous


def construire_stations(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Caractérise chaque station : type (trafic / fond), implantation, coordonnées, polluants."""
    noms = config["airparif"]["polluants"]
    infos = (
        df.groupby("station")
        .agg(nom=("nom", "first"), influence=("influence", "first"), implantation=("implantation", "first"))
    )
    mesures = df.dropna(subset=["valeur"]).groupby("station")["polluant"].agg(
        lambda s: ",".join(noms[p] for p in noms if p in set(s))
    )
    infos["polluants_mesures"] = mesures

    meta = extraction.charger_stations(config)
    coords = meta.set_index("EUStationCode")[["Latitude", "Longitude"]].rename(
        columns={"Latitude": "latitude", "Longitude": "longitude"}
    )
    infos = infos.join(coords)
    sans_coord = infos["latitude"].isna()
    if sans_coord.any():
        log.warning("Stations sans coordonnées : %s", ", ".join(infos.index[sans_coord]))
    infos["influence"] = infos["influence"].str.lower()
    return infos.reset_index()


def nettoyer(config: dict) -> dict[str, pd.DataFrame]:
    journal = Journal()
    brut = extraction.charger_brut(config)

    df = preparer(brut, config, journal)
    df = dedoublonner(df, journal)
    df = marquer_invalides(df, config, journal)
    df, anomalies = reperer_anomalies(df, config, journal)
    stations = construire_stations(df, config)
    mesures = passer_en_large(df, config, journal)
    couverture, trous = decrire_trous(mesures, config, journal)

    return {
        "mesures": mesures, "stations": stations, "anomalies": anomalies,
        "couverture": couverture, "trous": trous, "decisions": journal.table(),
    }


def sauvegarder(tables: dict[str, pd.DataFrame], config: dict) -> None:
    sortie = dossier(config, "interim", "airparif")
    for nom in TABLES:
        tables[nom].to_parquet(sortie / f"{nom}.parquet", index=False)
    tables["decisions"].to_csv(sortie / "decisions.csv", index=False)
    log.info("Tables écrites dans %s", sortie)


def charger(config: dict) -> dict[str, pd.DataFrame]:
    """Relit les tables nettoyées (pour les notebooks)."""
    sortie = dossier(config, "interim", "airparif")
    tables = {nom: pd.read_parquet(sortie / f"{nom}.parquet") for nom in TABLES}
    tables["decisions"] = pd.read_csv(sortie / "decisions.csv")
    return tables


if __name__ == "__main__":
    configurer_logs()
    c = charger_config()
    sauvegarder(nettoyer(c), c)
