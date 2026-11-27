"""Trafic et météo : le trafic baisse-t-il quand il pleut, gèle ou fait très chaud ?

Le trafic est ramené à une série Paris (débit moyen des arcs par heure) pour être joint
à la météo, puis comparé au débit habituel de la même heure de la semaine (débit relatif).
"""

import pandas as pd
import statsmodels.formula.api as smf

FUSEAU_PARIS = "Europe/Paris"


def trafic_par_heure(trafic: pd.DataFrame, part_arcs_min: float) -> pd.DataFrame:
    """Débit moyen des arcs par heure, sans les heures où trop peu d'arcs sont mesurés."""
    n_arcs = trafic["iu_ac"].nunique()
    par_heure = (
        trafic.groupby("heure")["q"]
        .agg(debit_moyen="mean", arcs_mesures="count")
        .reset_index()
    )
    par_heure["part_arcs"] = par_heure["arcs_mesures"] / n_arcs
    gardees = par_heure["part_arcs"] >= part_arcs_min
    return par_heure.loc[gardees, ["heure", "debit_moyen", "part_arcs"]].reset_index(
        drop=True
    )


def ajouter_debit_relatif(trafic_heure: pd.DataFrame) -> pd.DataFrame:
    """Ajoute heure_paris, jour_semaine, mois et debit_relatif (1 = trafic habituel)."""
    locale = trafic_heure["heure"].dt.tz_convert(FUSEAU_PARIS)
    df = trafic_heure.assign(
        heure_paris=locale.dt.hour,
        jour_semaine=locale.dt.dayofweek,
        mois=locale.dt.strftime("%Y-%m"),
    )
    debit_habituel = df.groupby(["jour_semaine", "heure_paris"])[
        "debit_moyen"
    ].transform("mean")
    df["debit_relatif"] = df["debit_moyen"] / debit_habituel
    return df


def joindre_meteo(
    trafic_heure: pd.DataFrame, meteo: pd.DataFrame, seuil_pluie_mm: float
) -> pd.DataFrame:
    """Jointure avec la météo sur l'heure (UTC) et colonne pluie."""
    colonnes = ["time", "precipitation", "temperature_2m", "wind_speed_10m"]
    meteo_heure = (
        meteo[colonnes].reset_index(drop=True).rename(columns={"time": "heure"})
    )
    df = trafic_heure.merge(meteo_heure, on="heure", how="inner", validate="one_to_one")
    df["pluie"] = df["precipitation"] > seuil_pluie_mm
    return df


def effet_pluie_par_heure(df: pd.DataFrame) -> pd.DataFrame:
    """Débit relatif moyen sec / pluie pour chaque heure de la journée."""
    moyennes = (
        df.groupby(["heure_paris", "pluie"])["debit_relatif"].mean().unstack("pluie")
    )
    moyennes.columns = ["sec" if not c else "pluie" for c in moyennes.columns]
    moyennes["heures_pluie"] = df[df["pluie"]].groupby("heure_paris").size()
    return moyennes


def effet_par_tranche(
    df: pd.DataFrame, colonne: str, bornes: list[float]
) -> pd.DataFrame:
    """Débit relatif moyen par tranche, brut et à mois égal (sans l'effet des vacances)."""
    tranches = pd.cut(df[colonne], bornes)
    a_mois_egal = df["debit_relatif"] / df.groupby("mois")["debit_relatif"].transform(
        "mean"
    )
    return pd.DataFrame(
        {
            "debit_relatif": df.groupby(tranches, observed=True)[
                "debit_relatif"
            ].mean(),
            "a_mois_egal": a_mois_egal.groupby(tranches, observed=True).mean(),
            "heures": df.groupby(tranches, observed=True).size(),
        }
    )


def regression_meteo(
    df: pd.DataFrame,
    bornes_temperature: list[float],
    tranche_reference: str,
    retards_hac: int,
):
    """MCO : écart au trafic habituel (%) ~ pluie + tranches de température + vent + mois.
    Écarts-types HAC car les heures successives sont corrélées."""
    donnees = df.assign(
        ecart=100 * (df["debit_relatif"] - 1),
        tranche_temperature=pd.cut(df["temperature_2m"], bornes_temperature).astype(
            str
        ),
        vent_10kmh=df["wind_speed_10m"] / 10,
        pluie=df["pluie"].astype(int),
    )
    formule = (
        f"ecart ~ pluie + C(tranche_temperature, Treatment('{tranche_reference}'))"
        " + vent_10kmh + C(mois)"
    )
    return smf.ols(formule, data=donnees).fit(
        cov_type="HAC", cov_kwds={"maxlags": retards_hac}
    )


def tableau_regression(modele) -> pd.DataFrame:
    """Coefficients météo (sans les effets fixes du mois) avec intervalle à 95 %."""
    intervalle = modele.conf_int()
    tableau = pd.DataFrame(
        {
            "effet (points de %)": modele.params,
            "IC 95 % bas": intervalle[0],
            "IC 95 % haut": intervalle[1],
            "p-valeur": modele.pvalues,
        }
    )
    tableau = tableau[~tableau.index.str.startswith(("Intercept", "C(mois)"))]
    tableau.index = [
        (
            "température " + nom.split("[T.", 1)[1][:-1]
            if nom.startswith("C(tranche")
            else {"pluie": "pluie (vs sec)", "vent_10kmh": "vent (+10 km/h)"}.get(
                nom, nom
            )
        )
        for nom in tableau.index
    ]
    temperatures = sorted(
        (n for n in tableau.index if n.startswith("température")),
        key=lambda n: float(n.split("(")[1].split(",")[0]),
    )
    return tableau.loc[["pluie (vs sec)", "vent (+10 km/h)", *temperatures]]
