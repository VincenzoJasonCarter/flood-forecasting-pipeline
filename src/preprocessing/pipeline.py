"""Full preprocessing pipeline, chaining every step of the package together."""

import pandas as pd

from .bigquery_io import authenticate, get_client, load_station_features
from .imputation import compute_hourly_medians, fill_nan_hourly_median
from .scaling import apply_scalers, fit_scalers, to_bq_column
from .splitting import get_station_cols, split_data
from .storage import save_metadata, save_preprocessed_data, save_scalers


def run():
    authenticate()
    client = get_client()

    df_fe = load_station_features(client)
    station_cols = get_station_cols(df_fe)
    print(f"Loaded: {df_fe.shape} | {df_fe.index[0].date()} → {df_fe.index[-1].date()}")
    print(f"Stations : {station_cols}")
    print(f"NaN total: {df_fe[station_cols].isna().sum().sum():,}")

    df_train_raw, df_val_raw, df_test_raw = split_data(df_fe)
    n = len(df_fe)
    print(f"Train : {df_train_raw.index[0].date()} → {df_train_raw.index[-1].date()} ({len(df_train_raw):,} rows, {len(df_train_raw)/n:.1%})")
    print(f"Val   : {df_val_raw.index[0].date()} → {df_val_raw.index[-1].date()} ({len(df_val_raw):,} rows, {len(df_val_raw)/n:.1%})")
    print(f"Test  : {df_test_raw.index[0].date()} → {df_test_raw.index[-1].date()} ({len(df_test_raw):,} rows, {len(df_test_raw)/n:.1%})")

    hourly_medians = compute_hourly_medians(df_train_raw, station_cols)
    print("Hourly medians per stasiun (cm):")
    for station, med in hourly_medians.items():
        print(f"  {station}: min={med.min():.1f} cm, max={med.max():.1f} cm")

    df_train_raw = fill_nan_hourly_median(df_train_raw, hourly_medians, station_cols)
    df_val_raw = fill_nan_hourly_median(df_val_raw, hourly_medians, station_cols)
    df_test_raw = fill_nan_hourly_median(df_test_raw, hourly_medians, station_cols)
    total_nan = (df_train_raw[station_cols].isna().sum().sum() +
                 df_val_raw[station_cols].isna().sum().sum() +
                 df_test_raw[station_cols].isna().sum().sum())
    print(f"\nTotal NaN tersisa: {total_nan}")

    scalers = fit_scalers(df_train_raw, station_cols)

    df_train = apply_scalers(df_train_raw, scalers, station_cols)
    df_val = apply_scalers(df_val_raw, scalers, station_cols)
    df_test = apply_scalers(df_test_raw, scalers, station_cols)
    print(f"Train range: {df_train[station_cols].min().min():.4f} – {df_train[station_cols].max().max():.4f}")
    print(f"Val   range: {df_val[station_cols].min().min():.4f} – {df_val[station_cols].max().max():.4f}")
    print(f"Test  range: {df_test[station_cols].min().min():.4f} – {df_test[station_cols].max().max():.4f}")

    # Nama stasiun (mis. "Bendung Katulampa") mengandung spasi yang tidak valid
    # sebagai nama kolom BigQuery, jadi disanitasi dulu (column_map) dan
    # disimpan di preprocessing_metadata agar notebook model bisa memetakan
    # baliknya.
    column_map = {station: to_bq_column(station) for station in station_cols}
    save_preprocessed_data(client, df_train, df_val, df_test, column_map)

    saved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
    save_metadata(client, station_cols, column_map, saved_at)
    save_scalers(client, scalers, saved_at)

    print("Saved: preprocessed_data, preprocessing_metadata, preprocessing_scalers -> BigQuery")
