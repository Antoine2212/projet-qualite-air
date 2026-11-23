"""NOx et trafic des axes proches de chaque station Airparif."""

import geopandas as gpd
import pandas as pd

FUSEAU_PARIS = "Europe/Paris"


def arcs_autour_des_stations(stations: gpd.GeoDataFrame, arcs: gpd.GeoDataFrame, rayon_m: float) -> pd.DataFrame:
    """Couples (station, iu_ac) des arcs à moins de rayon_m de la station (même projection en mètres)."""
    stations = stations.drop_duplicates("station")
    cercles = stations[["station", "geometry"]].assign(geometry=stations.buffer(rayon_m))
    liens = gpd.sjoin(cercles, arcs[["iu_ac", "geometry"]], predicate="intersects")
    return liens[["station", "iu_ac"]].reset_index(drop=True)


def trafic_autour_des_stations(trafic: pd.DataFrame, liens: pd.DataFrame, part_arcs_min: float) -> pd.DataFrame:
    """Débit moyen des arcs proches, par station et par heure (si assez d'arcs sont mesurés)."""
    n_arcs = liens.groupby("station").size().rename("n_arcs")
    par_heure = (
        trafic[["iu_ac", "heure", "q"]].merge(liens, on="iu_ac")
        .groupby(["station", "heure"])["q"].agg(trafic="mean", arcs_mesures="count")
        .reset_index()
        .merge(n_arcs, on="station")
    )
    gardees = par_heure["arcs_mesures"] >= part_arcs_min * par_heure["n_arcs"]
    return par_heure.loc[gardees, ["station", "heure", "trafic"]].reset_index(drop=True)


def joindre_air(trafic_station: pd.DataFrame, air: pd.DataFrame, stations: pd.DataFrame, polluant: str) -> pd.DataFrame:
    """Jointure sur (station, heure), puis valeurs relatives à la même heure de la semaine."""
    df = (
        trafic_station
        .merge(air[["station", "heure", polluant]], on=["station", "heure"])
        .dropna(subset=[polluant])
        .rename(columns={polluant: "pollution"})
        .merge(stations[["station", "nom", "influence"]].drop_duplicates("station"), on="station")
    )
    locale = df["heure"].dt.tz_convert(FUSEAU_PARIS)
    heure_semaine = locale.dt.dayofweek * 24 + locale.dt.hour
    for colonne in ["trafic", "pollution"]:
        habituel = df.groupby(["station", heure_semaine])[colonne].transform("mean")
        df[f"{colonne}_relatif"] = df[colonne] / habituel
    return df


def correlations_par_station(df: pd.DataFrame) -> pd.DataFrame:
    """Spearman trafic / pollution par station : brute et à heure de la semaine égale."""
    lignes = []
    for (station, nom, influence), g in df.groupby(["station", "nom", "influence"]):
        lignes.append({
            "station": station, "nom": nom, "influence": influence,
            "brute": g["trafic"].corr(g["pollution"], method="spearman"),
            "a_heure_egale": g["trafic_relatif"].corr(g["pollution_relatif"], method="spearman"),
            "heures": len(g),
        })
    return pd.DataFrame(lignes).sort_values("brute").reset_index(drop=True)


def pollution_par_decile(df: pd.DataFrame) -> pd.DataFrame:
    """Pollution moyenne par décile de trafic (déciles calculés station par station)."""
    decile = df.groupby("station")["trafic"].transform(lambda s: pd.qcut(s, 10, labels=False)) + 1
    return df.groupby([decile.rename("decile"), "influence"])["pollution"].mean().unstack("influence")


def sensibilite_rayon(stations, arcs, trafic, air, polluant, rayons, part_arcs_min) -> pd.DataFrame:
    """Corrélation médiane par type de station pour plusieurs rayons."""
    lignes = []
    for rayon in rayons:
        liens = arcs_autour_des_stations(stations, arcs, rayon)
        df = joindre_air(trafic_autour_des_stations(trafic, liens, part_arcs_min), air, stations, polluant)
        corr = correlations_par_station(df)
        for influence, g in corr.groupby("influence"):
            lignes.append({"rayon_m": rayon, "influence": influence, "stations": len(g),
                           "brute": g["brute"].median(), "a_heure_egale": g["a_heure_egale"].median()})
    return pd.DataFrame(lignes).set_index(["rayon_m", "influence"])
