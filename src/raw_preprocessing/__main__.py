"""CLI untuk raw preprocessing (API sisteminformasibanjir -> station_features_{hourly,daily}).

Pemakaian (dari src/):
    python -m raw_preprocessing
    python -m raw_preprocessing --granularity hourly
    python -m raw_preprocessing --start 2021-01-16 --end 2026-08-25
    python -m raw_preprocessing --output ../artifacts/df_fe.parquet
    python -m raw_preprocessing --write-bq
    python -m raw_preprocessing --incremental
    python -m raw_preprocessing --incremental --write-bq   # lanjut dari MAX(datetime) BigQuery, APPEND
"""

import argparse
from pathlib import Path

from . import run
from .config import GRANULARITIES, GRANULARITY, START_DATE


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default=START_DATE, help=f"Tanggal awal crawl (default: {START_DATE}).")
    parser.add_argument("--end", default=None, help="Tanggal akhir crawl, inklusif (default: hari ini).")
    parser.add_argument("--granularity", choices=GRANULARITIES, default=GRANULARITY,
                        help=f"Resolusi output (default dari config: {GRANULARITY}).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Path parquet output (default: artifacts/{tabel granularity}.parquet).")
    parser.add_argument("--write-bq", action="store_true",
                        help="Tulis ke tabel station_features_{granularity} di BigQuery: TIMPA (WRITE_TRUNCATE), "
                             "atau APPEND kalau dipakai bersama --incremental.")
    parser.add_argument("--incremental", action="store_true",
                        help="Crawl hanya dari beberapa hari sebelum tanggal terakhir di output lama "
                             "(--start diabaikan kalau output sudah ada), lalu gabungkan. Bersama --write-bq: "
                             "titik lanjut = MAX(datetime) tabel BigQuery dan baris baru di-APPEND.")
    args = parser.parse_args()

    run(start=args.start, end=args.end, granularity=args.granularity,
        output_path=args.output, write_bq=args.write_bq, incremental=args.incremental)


if __name__ == "__main__":
    main()
