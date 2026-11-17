"""Jalankan dashboard lokal: `make dashboard` / `python -m dashboard`."""

import argparse
import os

from logging_setup import configure_logging

import logging

from .app import RANGES, STEP_HOURS, app
from .data import start_refresher

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true", help="Dash debug mode (hot reload).")
    parser.add_argument("--demo", action="store_true",
                        help="Data PALSU dengan pos Siaga (dashboard/demo.py), tanpa BigQuery: lihat laporan saat banjir.")
    args = parser.parse_args()
    configure_logging()
    if args.demo:
        from .demo import install
        as_of, missing = install()
        logger.warning("MODE DEMO: data palsu per %s, BigQuery tidak dibaca%s", as_of,
                       f"; pos tanpa skenario: {sorted(missing)}" if missing else "")
    # mode debug memulai dua proses (pemuat ulang): pembaca latar belakang hanya di yang melayani
    elif not args.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_refresher({max(hours // STEP_HOURS, 1) for _, hours in RANGES.values()})
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
