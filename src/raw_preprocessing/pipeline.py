"""Full raw preprocessing pipeline, chaining every step of the package together."""

from datetime import date, timedelta

import pandas as pd

from .config import (
    CALENDAR_COLS,
    CLEAN_ISOLATED_SPIKES,
    GAP_LIMIT,
    GRANULARITIES,
    GRANULARITY,
    INCREMENTAL_OVERLAP_DAYS,
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
from .storage import (append_station_features, get_client, load_existing_features, save_parquet,
                      save_station_features)


def _resume_start(output_path, overlap_days):
    """Return (existing_df, start) untuk crawl incremental.

    Kalau output belum ada, existing_df None dan start None (caller jatuh
    ke full crawl)."""
    if not output_path.exists():
        return None, None
    existing = pd.read_parquet(output_path)
    if existing.empty:
        return None, None
    start = existing.index.max().date() - timedelta(days=overlap_days)
    return existing, start.isoformat()


def _bq_resume(client, table_id, overlap_days):
    """Seperti _resume_start, tapi titik lanjut diambil dari MAX(datetime) tabel BigQuery."""
    existing = load_existing_features(client, table_id)
    if existing is None:
        return None, None
    start = existing.index.max().date() - timedelta(days=overlap_days)
    return existing, start.isoformat()


def _merge_incremental(existing, new, start):
    """Gabungkan output lama dengan hasil crawl baru.

    Hari pertama window (`start`) hanya konteks interpolasi, jadi barisnya
    tetap dari `existing`; baris sejak `start` + 1 hari diganti hasil baru."""
    cut = pd.Timestamp(start) + timedelta(days=1)
    merged = pd.concat([existing[existing.index < cut], new[new.index >= cut]])
    stations = [c for c in merged.columns if c not in CALENDAR_COLS]
    return merged[stations + CALENDAR_COLS]


def run(start=START_DATE, end=None, granularity=GRANULARITY, output_path=None, write_bq=False,
        incremental=False, overlap_days=INCREMENTAL_OVERLAP_DAYS):
    """Jalankan pipeline.

    incremental=True: crawl hanya dari `overlap_days` hari sebelum tanggal
    terakhir di `output_path`, lalu gabungkan dengan output lama. Kalau output
    belum ada, jatuh ke full crawl dari `start`.

    incremental=True + write_bq=True: titik lanjut diambil dari MAX(datetime)
    tabel BigQuery (sumber kebenaran), dan hanya baris SETELAH max itu yang
    di-APPEND ke tabel. Hari-hari overlap hanya dipakai sebagai konteks
    interpolasi. Parquet lokal ditulis sebagai gabungan tabel lama + baris baru."""
    # Validasi sebelum crawl, supaya typo tidak baru ketahuan setelah crawl panjang.
    if granularity not in GRANULARITIES:
        raise ValueError(f"granularity harus salah satu dari {GRANULARITIES}, bukan {granularity!r}")
    end = end or date.today().isoformat()
    output_path = output_path or default_output_path(granularity)
    table_id = station_features_table(granularity)
    token = get_token()

    existing = None
    client = get_client() if write_bq else None
    bq_append = incremental and write_bq
    if incremental:
        if bq_append:
            existing, resume = _bq_resume(client, table_id, overlap_days)
            source = table_id
        else:
            existing, resume = _resume_start(output_path, overlap_days)
            source = output_path
        if existing is None:
            print(f"Incremental: {source} belum ada, full crawl dari {start}")
        else:
            start = resume
            print(f"Incremental: output lama s/d {existing.index.max()}, crawl ulang dari {start}")

    raw, failed = crawl_range(start, end, token)
    print(f"rows: {len(raw):,}, failed days: {len(failed)}")
    if failed:
        print(f"  failed: {failed}")
    if not raw:
        if existing is not None:
            print("Incremental: tidak ada data baru, output tidak diubah.")
            return existing
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

    if existing is not None and bq_append:
        last = existing.index.max()
        new_rows = df_fe[df_fe.index > last]
        extra = [c for c in new_rows.columns if c not in existing.columns]
        if extra:
            print(f"Peringatan: kolom tidak ada di tabel BigQuery, dilewati: {extra}")
        new_rows = new_rows.reindex(columns=existing.columns)
        if new_rows.empty:
            print(f"Incremental: tidak ada baris setelah {last}, tabel tidak diubah.")
            return existing
        append_station_features(client, new_rows, table_id)
        df_fe = pd.concat([existing, new_rows])
        print(f"Appended {len(new_rows):,} rows ({new_rows.index[0]} -> {new_rows.index[-1]})")
        save_parquet(df_fe, output_path)
        return df_fe

    if existing is not None:
        df_fe = _merge_incremental(existing, df_fe, start)
        print(f"Merged with existing output: {df_fe.shape} | {df_fe.index[0]} -> {df_fe.index[-1]}")

    save_parquet(df_fe, output_path)
    if write_bq:
        save_station_features(client, df_fe, table_id)
        print(f"Saved: {table_id} -> BigQuery")

    return df_fe
