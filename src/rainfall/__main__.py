"""CLI untuk rainfall (Open-Meteo -> rainfall_hourly).

Alur cepat (kuota API gratis kecil):
    python -m rainfall --survey --write-bq         # 1. semua sel, 1 musim hujan -> rainfall_survey (parquet + BQ)
    python -m rainfall.analysis                    # 2. ranking sel per stasiun
    python -m rainfall --select-top 3 --write-bq   # 3. histori penuh, top 3 sel per stasiun saja

Lainnya (dari src/):
    python -m rainfall --start 2025-01-01 --end 2025-01-31
    python -m rainfall --incremental --write-bq   # lanjut dari MAX(datetime) BigQuery
"""

import argparse
from pathlib import Path

import pandas as pd

from . import run
from .config import (RAINFALL_TABLE, RANKING_PATH, START_DATE, SURVEY_END, SURVEY_OUTPUT_PATH, SURVEY_START,
                     SURVEY_TABLE)
from .frames import select_top_cells


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default=None, help=f"Tanggal awal (default: {START_DATE}).")
    parser.add_argument("--end", default=None, help="Tanggal akhir, inklusif (default: hari ini).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Path parquet output (default: artifacts/rainfall_hourly.parquet).")
    parser.add_argument("--write-bq", action="store_true",
                        help="Juga TIMPA tabel BigQuery (WRITE_TRUNCATE): rainfall_hourly, "
                             "atau rainfall_survey_hourly dengan --survey.")
    parser.add_argument("--incremental", action="store_true",
                        help="Ambil ulang beberapa hari terakhir dari output lama lalu gabungkan "
                             "(--start diabaikan kalau output sudah ada). Bersama --write-bq: "
                             "output lama dibaca dari tabel BigQuery.")
    parser.add_argument("--survey", action="store_true",
                        help=f"Semua sel, periode survei {SURVEY_START}..{SURVEY_END} -> "
                             f"{SURVEY_OUTPUT_PATH.name} (untuk ranking); dengan --write-bq juga ke "
                             f"tabel terpisah {SURVEY_TABLE.split('.')[-1]}.")
    parser.add_argument("--select-top", type=int, default=None, metavar="N",
                        help="Hanya ambil N sel teratas per stasiun dari file ranking.")
    parser.add_argument("--ranking", type=Path, default=RANKING_PATH,
                        help=f"File ranking untuk --select-top (default: artifacts/{RANKING_PATH.name}).")
    args = parser.parse_args()

    start, end, output, table = args.start or START_DATE, args.end, args.output, RAINFALL_TABLE
    if args.survey:
        if args.incremental or args.select_top:
            parser.error("--survey tidak bisa digabung dengan --incremental/--select-top")
        start, end = args.start or SURVEY_START, args.end or SURVEY_END
        output, table = output or SURVEY_OUTPUT_PATH, SURVEY_TABLE

    cells = None
    if args.select_top:
        if not args.ranking.exists():
            parser.error(f"{args.ranking} belum ada; jalankan --survey lalu `python -m rainfall.analysis` dulu")
        cells = select_top_cells(pd.read_csv(args.ranking), args.select_top)
        print(f"Sel terpilih (top {args.select_top} per stasiun): {len(cells)}")

    run(start=start, end=end, output_path=output, write_bq=args.write_bq,
        incremental=args.incremental, cells=cells, table_id=table)


if __name__ == "__main__":
    main()
