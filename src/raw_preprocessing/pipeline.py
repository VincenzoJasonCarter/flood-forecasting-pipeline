"""Full raw preprocessing pipeline, chaining every step of the package together."""

from datetime import date

import pandas as pd

from .config import (
    CLEAN_ISOLATED_SPIKES,
    GAP_LIMIT,
    GRANULARITIES,
    GRANULARITY,
    START_DATE,
    default_output_path,
    station_features_table,
)
from .crawler import crawl_range, get_token
from .features import add_calendar_features
from .gaps import fill_gaps, gap_lengths
from .outliers import OUTLIER_COLS, clean_isolated_spikes, flag_outliers
from .parsing import flatten_records
from .resampling import resample_hourly, to_daily_max, to_wide
from .storage import get_client, save_parquet, save_station_features


def run(start=START_DATE, end=None, granularity=GRANULARITY, output_path=None, write_bq=False):
    # Validasi sebelum crawl, supaya typo tidak baru ketahuan setelah crawl panjang.
    if granularity not in GRANULARITIES:
        raise ValueError(f"granularity harus salah satu dari {GRANULARITIES}, bukan {granularity!r}")
    end = end or date.today().isoformat()
    output_path = output_path or default_output_path(granularity)
    table_id = station_features_table(granularity)
    token = get_token()

    raw, failed = crawl_range(start, end, token)
    print(f"rows: {len(raw):,}, failed days: {len(failed)}")
    if failed:
        print(f"  failed: {failed}")
    if not raw:
        raise RuntimeError(f"API tidak mengembalikan data untuk {start} -> {end}.")

    df = flatten_records(raw)
    df_long = resample_hourly(df)
    print(f"Resampled: {df_long.shape} | stations: {df_long['station_name'].nunique()}")

    df_long = flag_outliers(df_long)
    outlier_stats = (df_long.groupby("station_name")[OUTLIER_COLS].mean()
                     .sort_values("outlier_any", ascending=False))
    print("Outlier ratio per stasiun:")
    print(outlier_stats.round(4).to_string())
    if CLEAN_ISOLATED_SPIKES:
        df_long = clean_isolated_spikes(df_long)

    df_wide = to_wide(df_long)
    print(f"\nWide: {df_wide.shape[0]:,} rows x {df_wide.shape[1]} stations "
          f"| {df_wide.index[0]} -> {df_wide.index[-1]}")

    gap_summary = pd.DataFrame({
        station: {
            "missing_before": df_wide[station].isna().sum(),
            f"gaps_gt_{GAP_LIMIT}h": sum(1 for n in gap_lengths(df_wide[station]) if n > GAP_LIMIT),
        }
        for station in df_wide.columns
    }).T

    df_filled = fill_gaps(df_wide)
    gap_summary["missing_after"] = df_filled.isna().sum()
    print("Missing per stasiun (sebelum/sesudah pengisian gap):")
    print(gap_summary.sort_values("missing_before", ascending=False).to_string())

    if granularity == "daily":
        df_out = to_daily_max(df_filled)
        print(f"\nDaily max: {df_out.shape[0]:,} days x {df_out.shape[1]} stations "
              f"| days still NaN per stasiun: {df_out.isna().sum().to_dict()}")
    else:
        df_out = df_filled

    df_fe = add_calendar_features(df_out)
    print(f"\n{granularity} station features: {df_fe.shape} | holiday rows: {df_fe['is_holiday'].sum():,}")

    save_parquet(df_fe, output_path)
    if write_bq:
        save_station_features(get_client(), df_fe, table_id)
        print(f"Saved: {table_id} -> BigQuery")

    return df_fe
