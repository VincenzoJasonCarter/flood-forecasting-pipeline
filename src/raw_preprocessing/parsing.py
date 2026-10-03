"""Flattening raw API rows into a typed, de-duplicated long frame."""

import pandas as pd


def flatten_records(raw):
    """Flatten nested API rows -> satu baris per (stasiun, timestamp)."""
    df = pd.DataFrame([{
        "station_id"  : row["pos_pengamatan"]["id"],
        "station_name": row["pos_pengamatan"]["name"],
        "river"       : row["pos_pengamatan"]["aliran"],
        "datetime"    : row["tanggal"] + " " + row["jam"],
        "water_level" : row["ketinggian"],
        "alert_level" : row["status_siaga"],
        "weather"     : row["cuaca"]["nama"],
    } for row in raw])
    df["station_id"] = df["station_id"].astype(int)
    df["water_level"] = pd.to_numeric(df["water_level"], errors="coerce")
    df["alert_level"] = pd.to_numeric(df["alert_level"], errors="coerce").astype("Int64")
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")

    df = (df
          .drop_duplicates(subset=["station_id", "datetime"])
          .sort_values(["datetime", "station_id"])
          .reset_index(drop=True))

    # Dedup kedua per nama stasiun: resampling dan pivot dikunci oleh
    # station_name, jadi satu nama dengan >1 station_id tetap harus unik.
    return (df
            .sort_values(["station_name", "datetime"])
            .drop_duplicates(subset=["station_name", "datetime"]))
