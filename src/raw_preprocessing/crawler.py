"""HTTP crawler for the sisteminformasibanjir observation-post reports API."""

import os
import time
from datetime import date, timedelta

import requests

from .config import API_BASE_URL, API_TOKEN_ENV


def get_token():
    token = os.environ.get(API_TOKEN_ENV)
    if not token:
        raise RuntimeError(f"Env var {API_TOKEN_ENV} belum di-set (token API sisteminformasibanjir).")
    return token


def fetch_day(session, d, token, max_retries=5):
    """Ambil semua laporan pos pengamatan untuk satu tanggal (YYYY-MM-DD).

    Return list of rows, atau None kalau semua retry gagal.
    """
    for attempt in range(max_retries):
        try:
            r = session.get(
                f"{API_BASE_URL}/{d}",
                params={"format": "json"},
                headers={"token": token},
                timeout=15,
            )
            if r.status_code in (401, 403):
                raise RuntimeError(f"Token invalid (HTTP {r.status_code})")
            r.raise_for_status()
            return r.json().get("data", [])
        except (requests.RequestException, ValueError) as e:
            print(f"  retry {d}: {e}")
            time.sleep(2 ** attempt)
    return None


def crawl_range(start, end, token):
    """Crawl harian dari `start` sampai `end` (inklusif). Return (rows, failed_dates)."""
    cur, last = date.fromisoformat(start), date.fromisoformat(end)
    all_rows, failed = [], []

    with requests.Session() as session:
        while cur <= last:
            d = cur.isoformat()
            print("fetch", d)
            rows = fetch_day(session, d, token)

            if not rows:
                failed.append(d)
            else:
                all_rows.extend(rows)

            time.sleep(0.2)
            cur += timedelta(days=1)

    return all_rows, failed
