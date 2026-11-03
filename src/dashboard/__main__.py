"""Jalankan dashboard lokal: `make dashboard` / `python -m dashboard`."""

import argparse

from logging_setup import configure_logging

from .app import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true", help="Dash debug mode (hot reload).")
    args = parser.parse_args()
    configure_logging()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
