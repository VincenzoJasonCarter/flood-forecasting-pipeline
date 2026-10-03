"""CLI untuk preprocessing (station_features_{granularity} -> train/val/test, scalers, metadata).

Pemakaian (dari src/):
    python -m preprocessing
    python -m preprocessing --granularity hourly
"""

import argparse

from . import run
from .config import GRANULARITIES, GRANULARITY


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--granularity", choices=GRANULARITIES, default=GRANULARITY,
                        help=f"Set tabel input/output yang dipakai (default dari config: {GRANULARITY}).")
    args = parser.parse_args()

    run(granularity=args.granularity)


if __name__ == "__main__":
    main()
