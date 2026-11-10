"""Full preprocessing pipeline, chaining every step of the package together."""

import logging

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

logger = logging.getLogger(__name__)


def _rain_cells(station_cols):
    """Sel hujan per stasiun dari file ranking (hasil `make rainfall-rank`)."""
    if not RAIN_RANKING_PATH.exists():
        raise FileNotFoundError(
            f"{RAIN_RANKING_PATH} belum ada. Jalankan `make rainfall-survey` lalu `make rainfall-rank`, "
            f"atau set rainfall.enabled: false di config/preprocessing.yaml.")
    cells = top_cells_by_station(pd.read_csv(RAIN_RANKING_PATH), RAIN_TOP_CELLS)
    skipped = [s for s in station_cols if s not in cells]
    if skipped:
        logger.warning("Tidak ada ranking hujan untuk %s; stasiun ini tanpa fitur hujan.", skipped)
    return {s: cells[s] for s in station_cols if s in cells}


def run(granularity=GRANULARITY):
    if granularity not in GRANULARITIES:
        raise ValueError(f"granularity harus salah satu dari {GRANULARITIES}, bukan {granularity!r}")
    authenticate()
    client = get_client()

    df_fe = load_station_features(client, table_id("station_features", granularity))
    station_cols = get_station_cols(df_fe)
    logger.info("Loaded: %s | %s → %s", df_fe.shape, df_fe.index[0].date(), df_fe.index[-1].date())
    logger.info("Stations : %s", station_cols)
    logger.info("NaN total: %s", f"{df_fe[station_cols].isna().sum().sum():,}")

    df_train_raw, df_val_raw, df_test_raw = split_data(df_fe)
    n = len(df_fe)
    for label, part in (("Train", df_train_raw), ("Val", df_val_raw), ("Test", df_test_raw)):
        logger.info("%-5s : %s → %s (%s rows, %.1f%%)", label, part.index[0].date(), part.index[-1].date(),
                    f"{len(part):,}", 100 * len(part) / n)

    # Untuk data daily index.hour selalu 0, jadi ini jadi median keseluruhan per stasiun.
    hourly_medians = compute_hourly_medians(df_train_raw, station_cols)
    logger.info("Hourly medians per stasiun (cm):")
    for station, med in hourly_medians.items():
        logger.info("  %s: min=%.1f cm, max=%.1f cm", station, med.min(), med.max())

    df_train_raw = fill_nan_hourly_median(df_train_raw, hourly_medians, station_cols)
    df_val_raw = fill_nan_hourly_median(df_val_raw, hourly_medians, station_cols)
    df_test_raw = fill_nan_hourly_median(df_test_raw, hourly_medians, station_cols)
    total_nan = (df_train_raw[station_cols].isna().sum().sum() +
                 df_val_raw[station_cols].isna().sum().sum() +
                 df_test_raw[station_cols].isna().sum().sum())
    logger.info("Total NaN tersisa: %s", total_nan)

    scalers = fit_scalers(df_train_raw, station_cols)

    df_train = encode_calendar(apply_scalers(df_train_raw, scalers, station_cols))
    df_val = encode_calendar(apply_scalers(df_val_raw, scalers, station_cols))
    df_test = encode_calendar(apply_scalers(df_test_raw, scalers, station_cols))
    for label, part in (("Train", df_train), ("Val", df_val), ("Test", df_test)):
        logger.info("%-5s range: %.4f – %.4f", label, part[station_cols].min().min(), part[station_cols].max().max())

    # Nama stasiun (mis. "Bendung Katulampa") mengandung spasi yang tidak valid
    # sebagai nama kolom BigQuery, jadi disanitasi dulu (column_map) dan
    # disimpan di preprocessing_metadata agar notebook model bisa memetakan
    # baliknya.
    column_map = {station: to_bq_column(station) for station in station_cols}

    rain_cells, rain_cols = {}, {}
    if RAIN_ENABLED and granularity != "hourly":
        logger.info("Fitur hujan hanya untuk granularity hourly; dilewati.")
    elif RAIN_ENABLED:
        rain_cells = _rain_cells(station_cols)
        all_cells = sorted({c for cells in rain_cells.values() for c in cells})
        rain = load_rainfall_cells(client, RAIN_TABLE, all_cells)
        logger.info("Hujan: %d sel dari %s | %s → %s", len(all_cells), RAIN_TABLE, rain.index[0], rain.index[-1])
        # Dihitung di seluruh histori sekaligus, supaya jendela akumulasi di
        # awal val/test tetap memakai jam-jam terakhir periode sebelumnya.
        features, rain_cols = rain_features(rain, rain_cells, RAIN_ACCUM_HOURS, column_map, df_fe.index)
        all_rain_cols = [c for cols in rain_cols.values() for c in cols]
        rain_scalers = fit_rain_scalers(features.loc[df_train.index], all_rain_cols)
        features = apply_rain_scalers(features, rain_scalers, all_rain_cols)
        df_train, df_val, df_test = (d.join(features) for d in (df_train, df_val, df_test))
        scalers.update(rain_scalers)
        for station, cols in rain_cols.items():
            logger.info("  %s: %d sel -> %s", station, len(rain_cells[station]), cols)

    save_preprocessed_data(client, df_train, df_val, df_test, column_map,
                           table_id("preprocessed_data", granularity))

    saved_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
    metadata = build_metadata(station_cols, column_map, hourly_medians, granularity,
                              rain_cells, rain_cols, RAIN_ACCUM_HOURS if rain_cols else ())
    save_metadata(client, metadata, saved_at, table_id("metadata", granularity))
    save_scalers(client, scalers, saved_at, table_id("scalers", granularity))

    logger.info("Saved (%s): preprocessed_data, metadata, scalers -> BigQuery", granularity)
