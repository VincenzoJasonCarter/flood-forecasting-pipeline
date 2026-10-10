"""Prepare the freshest raw data the same way `preprocessing` prepared training data."""

import json

from preprocessing.bigquery_io import load_rainfall_cells, load_station_features
from preprocessing.features import apply_rain_scalers, encode_calendar, rain_features
from preprocessing.imputation import compute_hourly_medians, fill_nan_hourly_median, medians_from_json
from preprocessing.scaling import apply_scalers
from preprocessing.splitting import split_data

from .config import LOOKBACK, METADATA_TABLE, RAINFALL_TABLE, STATION_FEATURES_TABLE
from .features import required_history
from .scalers import load_scalers


def load_metadata(client):
    row = client.query(f"""
        SELECT payload
        FROM `{METADATA_TABLE}`
        ORDER BY saved_at DESC
        LIMIT 1
    """).to_dataframe().iloc[0]
    return json.loads(row["payload"])


def load_recent_scaled(client, lookback=LOOKBACK, use_rain=True):
    """Ambil `lookback` langkah (jam/hari) data terakhir dan bangun fiturnya
    persis seperti `preprocessing`: isi NaN (median periode training dari
    metadata), scale stasiun, encode kalender (sin/cos), dan tambah fitur
    hujan per stasiun (kalau ada di metadata dan `use_rain`).

    Metadata lama (tanpa `fill_medians`/`calendar_feature_cols`) tetap
    didukung: median dihitung ulang dari histori dan kalender tidak di-encode.

    Return: (df_recent_scaled, metadata, scalers). df berisi semua kolom
    fitur; pilih kolom per stasiun dengan `features.feature_cols_for`.
    """
    metadata = load_metadata(client)
    station_cols = metadata["station_cols"]

    df_fe = load_station_features(client, STATION_FEATURES_TABLE)
    if "fill_medians" in metadata:
        hourly_medians = medians_from_json(metadata["fill_medians"])
    else:
        df_train_raw, _, _ = split_data(df_fe)
        hourly_medians = compute_hourly_medians(df_train_raw, station_cols)

    df_recent_raw = df_fe.tail(required_history(metadata, lookback))
    df_recent_filled = fill_nan_hourly_median(df_recent_raw, hourly_medians, station_cols)

    scalers = load_scalers(client)
    df_scaled = apply_scalers(df_recent_filled, scalers, station_cols)
    if "calendar_feature_cols" in metadata:
        df_scaled = encode_calendar(df_scaled)

    rain_cells = metadata.get("rain_cells_by_station") or {}
    if use_rain and rain_cells:
        cells = sorted({c for station_cells in rain_cells.values() for c in station_cells})
        rain = load_rainfall_cells(client, RAINFALL_TABLE, cells, since=df_scaled.index[0])
        features, rain_cols = rain_features(rain, rain_cells, metadata["rain_accum_hours"],
                                            metadata["column_map"], df_scaled.index)
        all_rain_cols = [c for cols in rain_cols.values() for c in cols]
        df_scaled = df_scaled.join(apply_rain_scalers(features, scalers, all_rain_cols))

    return df_scaled.tail(lookback), metadata, scalers
