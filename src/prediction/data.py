"""Prepare the freshest raw data the same way 00_Preprocessing prepared training data."""

import json

from preprocessing.bigquery_io import load_station_features
from preprocessing.imputation import compute_hourly_medians, fill_nan_hourly_median
from preprocessing.scaling import apply_scalers
from preprocessing.splitting import split_data

from .config import LOOKBACK, METADATA_TABLE, STATION_FEATURES_TABLE
from .scalers import load_scalers


def load_metadata(client):
    row = client.query(f"""
        SELECT payload
        FROM `{METADATA_TABLE}`
        ORDER BY saved_at DESC
        LIMIT 1
    """).to_dataframe().iloc[0]
    return json.loads(row["payload"])


def load_recent_scaled(client, lookback=LOOKBACK):
    """Ambil `lookback` jam data terakhir, isi NaN (hourly median dari periode
    training) lalu scale dengan scaler yang sama dengan training.

    Train split dihitung ulang dari seluruh histori `station_features` (sama
    seperti 00_Preprocessing) untuk mendapat hourly median yang konsisten;
    ini cukup murah dibanding training model itu sendiri, tapi berarti
    boundary train/val/test bisa bergeser sedikit begitu ada data baru masuk.

    Return: (df_recent_scaled, feature_cols, station_cols, scalers)
    """
    metadata = load_metadata(client)
    feature_cols = metadata["feature_cols"]
    station_cols = metadata["station_cols"]

    df_fe = load_station_features(client, STATION_FEATURES_TABLE)
    df_train_raw, _, _ = split_data(df_fe)
    hourly_medians = compute_hourly_medians(df_train_raw, station_cols)

    df_recent_raw = df_fe.tail(lookback)
    df_recent_filled = fill_nan_hourly_median(df_recent_raw, hourly_medians, station_cols)

    scalers = load_scalers(client)
    df_recent_scaled = apply_scalers(df_recent_filled, scalers, station_cols)

    return df_recent_scaled[feature_cols], feature_cols, station_cols, scalers
