"""Jalankan dashboard lokal: `make dashboard` / `python -m dashboard`."""

import argparse
import os

from logging_setup import configure_logging

from .app import RANGES, STEP_HOURS, app
from .data import start_refresher


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true", help="Dash debug mode (hot reload).")
    args = parser.parse_args()
    configure_logging()
    # mode debug memulai dua proses (pemuat ulang): pembaca latar belakang hanya di yang melayani
    if not args.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_refresher({max(hours // STEP_HOURS, 1) for _, hours in RANGES.values()})
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
