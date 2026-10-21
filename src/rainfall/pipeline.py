"""Full rainfall pipeline: discover grid cells, fetch hourly precipitation, merge, save."""

import logging
from datetime import date, timedelta

import pandas as pd
import requests

from .client import RateLimited, Throttle, discover_cells, fetch_range, total_weight
from .config import BBOX, DEFAULT_OUTPUT_PATH, OVERLAP_DAYS, PROBE_STEP, RAINFALL_TABLE, START_DATE, TIMEZONE
from .frames import candidate_points, drop_future, merge_incremental, parse_cell_column
from .storage import get_client, load_parquet, load_rainfall, save_parquet, save_rainfall

logger = logging.getLogger(__name__)


def run(start=START_DATE, end=None, output_path=None, write_bq=False, incremental=False,
        overlap_days=OVERLAP_DAYS, now=None, cells=None, table_id=RAINFALL_TABLE):
    """Jalankan pipeline.

    cells: daftar (lat, lon) sel yang diambil (mis. hasil select_top_cells);
    default semua sel di kotak grid config. table_id: tabel BigQuery tujuan
    (write_bq) dan sumber output lama (incremental + write_bq).

    incremental=True: ambil ulang mulai `overlap_days` hari sebelum tanggal
    terakhir output lama (parquet, atau tabel BigQuery kalau write_bq), dengan
    sel grid yang sama (dibaca dari nama kolom, `cells` diabaikan). Kalau
    output belum ada, jatuh ke full fetch dari `start`.

    Request ditunda otomatis supaya tidak melewati kuota per menit/jam. Kalau
    berhenti di tengah jalan (kuota harian habis, Ctrl+C, atau error lain),
    potongan waktu yang sudah lengkap tetap disimpan dulu (error lain lalu
    dilempar ulang); lanjutkan nanti dengan incremental=True."""
    end = end or date.today().isoformat()
    output_path = output_path or DEFAULT_OUTPUT_PATH
    now = now or pd.Timestamp.now(tz=TIMEZONE).tz_localize(None)
    client = get_client() if write_bq else None

    existing = None
    if incremental:
        existing = load_rainfall(client, table_id) if write_bq else load_parquet(output_path)
        source = table_id if write_bq else output_path
        if existing is None:
            logger.info("Incremental: %s belum ada, full fetch dari %s", source, start)
        else:
            start = (existing.index.max().date() - timedelta(days=overlap_days)).isoformat()
            cells = [parse_cell_column(c) for c in existing.columns]
            logger.info("Incremental: output lama s/d %s (%d sel), ambil ulang dari %s", existing.index.max(), len(cells), start)

    frames, stopped, error = [], None, None
    throttle = Throttle()
    with requests.Session() as session:
        if cells is None:
            cells = discover_cells(session, throttle, candidate_points(*BBOX, PROBE_STEP))
            logger.info("Grid: %d sel di kotak lat %s..%s, lon %s..%s", len(cells), *BBOX)
        logger.info("Perkiraan bobot kuota: %s (kuota gratis 5.000/jam, 10.000/hari)",
                    f"{total_weight(len(cells), start, end):,.0f}")
        try:
            for frame in fetch_range(session, throttle, cells, start, end):
                frames.append(frame)
                logger.info("fetched %s -> %s", frame.index[0], frame.index[-1])
        except (RateLimited, KeyboardInterrupt) as e:
            if not frames:
                raise
            stopped = str(e) or "dihentikan"
        except Exception as e:  # mis. jaringan putus setelah semua retry
            if not frames:
                raise
            stopped, error = f"error: {e}", e

    df = drop_future(pd.concat(frames), now)
    if existing is not None:
        df = merge_incremental(existing, df, start)
    logger.info("Rainfall: %s | %s -> %s | NaN: %s", df.shape, df.index[0], df.index[-1], f"{int(df.isna().sum().sum()):,}")

    save_parquet(df, output_path)
    if write_bq:
        save_rainfall(client, df, table_id)
        logger.info("Saved: %s -> BigQuery", table_id)
    if stopped:
        logger.warning("Berhenti sebelum selesai (%s). Data tersimpan s/d %s; lanjutkan nanti dengan --incremental.",
                       stopped, df.index[-1])
    if error is not None:
        raise error
    return df
