"""CLI untuk raw preprocessing (API sisteminformasibanjir -> station_features_{hourly,daily}).

Pemakaian (dari src/):
    python -m raw_preprocessing
    python -m raw_preprocessing --granularity hourly
    python -m raw_preprocessing --start 2021-01-16 --end 2026-08-25
    python -m raw_preprocessing --output ../artifacts/df_fe.parquet
    python -m raw_preprocessing --write-bq
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
                        help="Juga TIMPA tabel station_features_{granularity} di BigQuery (WRITE_TRUNCATE).")
    args = parser.parse_args()

    run(start=args.start, end=args.end, granularity=args.granularity,
        output_path=args.output, write_bq=args.write_bq)


if __name__ == "__main__":
    main()
