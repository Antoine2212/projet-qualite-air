import requests
import pandas as pd
from pathlib import Path

# Fonction d'extraction du data set meteo

def meteo_dataset_extraction():
    START_DATE = "2025-09-01"
    END_DATE = "2026-08-31"

    # Coordonnées de Paris
    LATITUDE = 48.8566
    LONGITUDE = 2.3522

    # Dossier des données brutes
    DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
    DATA_DIR.mkdir(parents=True, exist_ok=True)


    url = "https://archive-api.open-meteo.com/v1/archive"

    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "hourly": [
            "temperature_2m",
            "relative_humidity_2m",
            "dew_point_2m",
            "apparent_temperature",
            "precipitation",
            "rain",
            "snowfall",
            "snow_depth",
            "surface_pressure",
            "pressure_msl",
            "cloud_cover",
            "cloud_cover_low",
            "cloud_cover_mid",
            "cloud_cover_high",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_speed_100m",
            "wind_direction_100m",
            "wind_gusts_10m",
            "shortwave_radiation",
            "soil_temperature_0_to_7cm",
            "soil_moisture_0_to_7cm",
            "is_day",
        ],
        "timezone": "UTC",
    }

    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()

    # Sauvegarde de la réponse JSON brute
    with open(DATA_DIR / "meteo.json", "wb") as f:
        f.write(response.content)

    # Conversion en DataFrame pour l'exploration
    df_meteo = pd.DataFrame(response.json()["hourly"])

    return df_meteo
