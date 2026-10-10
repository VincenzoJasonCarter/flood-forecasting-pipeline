"""Full preprocessing pipeline, chaining every step of the package together."""

import pandas as pd

from .bigquery_io import authenticate, get_client, load_rainfall_cells, load_station_features
from .config import (GRANULARITIES, GRANULARITY, RAIN_ACCUM_HOURS, RAIN_ENABLED, RAIN_RANKING_PATH, RAIN_TABLE,
                     RAIN_TOP_CELLS, table_id)
from .features import apply_rain_scalers, encode_calendar, fit_rain_scalers, rain_features, top_cells_by_station
from .imputation import compute_hourly_medians, fill_nan_hourly_median
from .metadata import build_metadata
from .scaling import apply_scalers, fit_scalers, to_bq_column
from .splitting import get_station_cols, split_data
from .storage import save_metadata, save_preprocessed_data, save_scalers


def _rain_cells(station_cols):
    """Sel hujan per stasiun dari file ranking (hasil `make rainfall-rank`)."""
    if not RAIN_RANKING_PATH.exists():
        raise FileNotFoundError(
            f"{RAIN_RANKING_PATH} belum ada. Jalankan `make rainfall-survey` lalu `make rainfall-rank`, "
            f"atau set rainfall.enabled: false di config/preprocessing.yaml.")
    cells = top_cells_by_station(pd.read_csv(RAIN_RANKING_PATH), RAIN_TOP_CELLS)
    skipped = [s for s in station_cols if s not in cells]
    if skipped:
        print(f"Peringatan: tidak ada ranking hujan untuk {skipped}; stasiun ini tanpa fitur hujan.")
    return {s: cells[s] for s in station_cols if s in cells}


def run(granularity=GRANULARITY):
    if granularity not in GRANULARITIES:
        raise ValueError(f"granularity harus salah satu dari {GRANULARITIES}, bukan {granularity!r}")
    authenticate()
    client = get_client()

    df_fe = load_station_features(client, table_id("station_features", granularity))
    station_cols = get_station_cols(df_fe)
    print(f"Loaded: {df_fe.shape} | {df_fe.index[0].date()} → {df_fe.index[-1].date()}")
    print(f"Stations : {station_cols}")
    print(f"NaN total: {df_fe[station_cols].isna().sum().sum():,}")

    df_train_raw, df_val_raw, df_test_raw = split_data(df_fe)
    n = len(df_fe)
    print(f"Train : {df_train_raw.index[0].date()} → {df_train_raw.index[-1].date()} ({len(df_train_raw):,} rows, {len(df_train_raw)/n:.1%})")
    print(f"Val   : {df_val_raw.index[0].date()} → {df_val_raw.index[-1].date()} ({len(df_val_raw):,} rows, {len(df_val_raw)/n:.1%})")
    print(f"Test  : {df_test_raw.index[0].date()} → {df_test_raw.index[-1].date()} ({len(df_test_raw):,} rows, {len(df_test_raw)/n:.1%})")

    # Untuk data daily index.hour selalu 0, jadi ini jadi median keseluruhan per stasiun.
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

    df_train = encode_calendar(apply_scalers(df_train_raw, scalers, station_cols))
    df_val = encode_calendar(apply_scalers(df_val_raw, scalers, station_cols))
    df_test = encode_calendar(apply_scalers(df_test_raw, scalers, station_cols))
    print(f"Train range: {df_train[station_cols].min().min():.4f} – {df_train[station_cols].max().max():.4f}")
    print(f"Val   range: {df_val[station_cols].min().min():.4f} – {df_val[station_cols].max().max():.4f}")
    print(f"Test  range: {df_test[station_cols].min().min():.4f} – {df_test[station_cols].max().max():.4f}")

    # Nama stasiun (mis. "Bendung Katulampa") mengandung spasi yang tidak valid
    # sebagai nama kolom BigQuery, jadi disanitasi dulu (column_map) dan
    # disimpan di preprocessing_metadata agar notebook model bisa memetakan
    # baliknya.
    column_map = {station: to_bq_column(station) for station in station_cols}

    rain_cells, rain_cols = {}, {}
    if RAIN_ENABLED and granularity != "hourly":
        print("Fitur hujan hanya untuk granularity hourly; dilewati.")
    elif RAIN_ENABLED:
        rain_cells = _rain_cells(station_cols)
        all_cells = sorted({c for cells in rain_cells.values() for c in cells})
        rain = load_rainfall_cells(client, RAIN_TABLE, all_cells)
        print(f"\nHujan: {len(all_cells)} sel dari {RAIN_TABLE} | {rain.index[0]} → {rain.index[-1]}")
        # Dihitung di seluruh histori sekaligus, supaya jendela akumulasi di
        # awal val/test tetap memakai jam-jam terakhir periode sebelumnya.
        features, rain_cols = rain_features(rain, rain_cells, RAIN_ACCUM_HOURS, column_map, df_fe.index)
        all_rain_cols = [c for cols in rain_cols.values() for c in cols]
        rain_scalers = fit_rain_scalers(features.loc[df_train.index], all_rain_cols)
        features = apply_rain_scalers(features, rain_scalers, all_rain_cols)
        df_train, df_val, df_test = (d.join(features) for d in (df_train, df_val, df_test))
        scalers.update(rain_scalers)
        for station, cols in rain_cols.items():
            print(f"  {station}: {len(rain_cells[station])} sel -> {cols}")

    save_preprocessed_data(client, df_train, df_val, df_test, column_map,
                           table_id("preprocessed_data", granularity))

    saved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
    metadata = build_metadata(station_cols, column_map, hourly_medians, granularity,
                              rain_cells, rain_cols, RAIN_ACCUM_HOURS if rain_cols else ())
    save_metadata(client, metadata, saved_at, table_id("metadata", granularity))
    save_scalers(client, scalers, saved_at, table_id("scalers", granularity))

    print(f"Saved ({granularity}): preprocessed_data, metadata, scalers -> BigQuery")
