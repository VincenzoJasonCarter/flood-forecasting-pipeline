"""Full rainfall pipeline: discover grid cells, fetch hourly precipitation, merge, save."""

from datetime import date, timedelta

import pandas as pd
import requests

from .client import RateLimited, Throttle, discover_cells, fetch_range, total_weight
from .config import BBOX, DEFAULT_OUTPUT_PATH, OVERLAP_DAYS, PROBE_STEP, RAINFALL_TABLE, START_DATE, TIMEZONE
from .frames import candidate_points, drop_future, merge_incremental, parse_cell_column
from .storage import get_client, load_parquet, load_rainfall, save_parquet, save_rainfall


def run(start=START_DATE, end=None, output_path=None, write_bq=False, incremental=False,
        overlap_days=OVERLAP_DAYS, now=None, cells=None):
    """Jalankan pipeline.

    cells: daftar (lat, lon) sel yang diambil (mis. hasil select_top_cells);
    default semua sel di kotak grid config.

    incremental=True: ambil ulang mulai `overlap_days` hari sebelum tanggal
    terakhir output lama (parquet, atau tabel BigQuery kalau write_bq), dengan
    sel grid yang sama (dibaca dari nama kolom, `cells` diabaikan). Kalau
    output belum ada, jatuh ke full fetch dari `start`.

    Request ditunda otomatis supaya tidak melewati kuota per menit/jam. Kalau
    kuota harian habis (atau Ctrl+C), potongan waktu yang sudah lengkap tetap
    disimpan; lanjutkan nanti dengan incremental=True."""
    end = end or date.today().isoformat()
    output_path = output_path or DEFAULT_OUTPUT_PATH
    now = now or pd.Timestamp.now(tz=TIMEZONE).tz_localize(None)
    client = get_client() if write_bq else None

    existing = None
    if incremental:
        existing = load_rainfall(client, RAINFALL_TABLE) if write_bq else load_parquet(output_path)
        source = RAINFALL_TABLE if write_bq else output_path
        if existing is None:
            print(f"Incremental: {source} belum ada, full fetch dari {start}")
        else:
            start = (existing.index.max().date() - timedelta(days=overlap_days)).isoformat()
            cells = [parse_cell_column(c) for c in existing.columns]
            print(f"Incremental: output lama s/d {existing.index.max()} ({len(cells)} sel), ambil ulang dari {start}")

    frames, stopped = [], None
    throttle = Throttle()
    with requests.Session() as session:
        if cells is None:
            cells = discover_cells(session, throttle, candidate_points(*BBOX, PROBE_STEP))
            print(f"Grid: {len(cells)} sel di kotak lat {BBOX[0]}..{BBOX[1]}, lon {BBOX[2]}..{BBOX[3]}")
        print(f"Perkiraan bobot kuota: {total_weight(len(cells), start, end):,.0f} "
              f"(kuota gratis 5.000/jam, 10.000/hari)")
        try:
            for frame in fetch_range(session, throttle, cells, start, end):
                frames.append(frame)
                print(f"  fetched {frame.index[0]} -> {frame.index[-1]}")
        except (RateLimited, KeyboardInterrupt) as e:
            if not frames:
                raise
            stopped = str(e) or "dihentikan"

    df = drop_future(pd.concat(frames), now)
    if existing is not None:
        df = merge_incremental(existing, df, start)
    print(f"Rainfall: {df.shape} | {df.index[0]} -> {df.index[-1]} | NaN: {int(df.isna().sum().sum()):,}")

    save_parquet(df, output_path)
    if write_bq:
        save_rainfall(client, df, RAINFALL_TABLE)
        print(f"Saved: {RAINFALL_TABLE} -> BigQuery")
    if stopped:
        print(f"\nBerhenti sebelum selesai ({stopped}). Data tersimpan s/d {df.index[-1]}; "
              f"lanjutkan nanti dengan --incremental.")
    return df
