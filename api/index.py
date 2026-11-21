"""Entrypoint Vercel (serverless): menyajikan Flask server milik Dash.

Tidak memanggil start_refresher: thread latar belakang tidak hidup di serverless.
load_snapshot tetap membaca BigQuery secara lazy dengan cache per instance.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dashboard.app import server  # noqa: E402

app = server
