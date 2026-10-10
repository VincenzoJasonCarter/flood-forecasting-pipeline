"""HTTP client for the Open-Meteo Historical Forecast API (hourly precipitation)."""

import time
from collections import deque
from datetime import date

import requests

from .config import (API_URL, CELLS_PER_REQUEST, DAYS_PER_REQUEST, HOUR_BUDGET, MINUTE_BUDGET, MODEL,
                     START_DATE, TIMEZONE, VARIABLE)
from .frames import date_chunks, dedupe_cells, responses_to_frame


class RateLimited(RuntimeError):
    """Kuota API gratis Open-Meteo (per jam/hari) habis."""


def request_weight(n_locations, n_days, n_variables=1):
    """Bobot kuota satu request: tiap lokasi dihitung terpisah, dan request
    > 14 hari atau > 10 variabel dihitung sebagai beberapa call."""
    return n_locations * max(1.0, n_days / 14) * max(1.0, n_variables / 10)


class Throttle:
    """Tunda request supaya total bobot dalam tiap jendela waktu tetap di
    bawah anggarannya (default: per menit dan per jam dari config)."""

    def __init__(self, limits=((60, MINUTE_BUDGET), (3600, HOUR_BUDGET)),
                 clock=time.monotonic, sleep=time.sleep):
        self.limits = limits
        self.clock = clock
        self.sleep = sleep
        self.history = deque()  # (waktu, bobot), terurut

    def _delay(self, weight, now):
        delay = 0.0
        for window, budget in self.limits:
            if weight > budget:
                raise ValueError(f"Bobot 1 request ({weight:.0f}) > anggaran {budget} per {window} detik; "
                                 f"kecilkan cells_per_request/days_per_request.")
            recent = [(t, w) for t, w in self.history if t > now - window]
            excess = sum(w for _, w in recent) + weight - budget
            for t, w in recent:  # tunggu sampai entri tertua cukup banyak yang kedaluwarsa
                if excess <= 0:
                    break
                excess -= w
                delay = max(delay, t + window - now)
        return delay

    def wait(self, weight):
        while True:
            now = self.clock()
            longest = max(window for window, _ in self.limits)
            while self.history and self.history[0][0] <= now - longest:
                self.history.popleft()
            delay = self._delay(weight, now)
            if delay <= 0:
                self.history.append((now, weight))
                return
            if delay > 90:
                print(f"  kuota per jam hampir habis, menunggu {delay / 60:.0f} menit "
                      f"(Ctrl+C untuk berhenti; data yang sudah lengkap tetap disimpan)")
            self.sleep(delay + 1)


def _reason(r):
    try:
        return r.json().get("reason", r.text)
    except ValueError:
        return r.text


def fetch(session, throttle, points, start, end, max_retries=5):
    """Satu request untuk beberapa titik sekaligus. Return list respons, satu
    per titik dengan urutan yang sama."""
    n_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    params = {
        "latitude": ",".join(str(lat) for lat, _ in points),
        "longitude": ",".join(str(lon) for _, lon in points),
        "start_date": start,
        "end_date": end,
        "hourly": VARIABLE,
        "models": MODEL,
        "timezone": TIMEZONE,
    }
    attempt = 0
    while attempt < max_retries:
        throttle.wait(request_weight(len(points), n_days))
        try:
            r = session.get(API_URL, params=params, timeout=120)
        except requests.RequestException as e:
            print(f"  retry {start}..{end}: {e}")
            attempt += 1
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429:
            reason = _reason(r)
            if "Minutely" not in reason:  # kuota per jam/hari: tidak ditunggu di sini
                raise RateLimited(reason)
            print("  kuota per menit habis, menunggu 60 detik")
            time.sleep(61)
            continue
        if r.status_code >= 500:
            print(f"  retry {start}..{end}: HTTP {r.status_code}")
            attempt += 1
            time.sleep(2 ** attempt)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Open-Meteo HTTP {r.status_code}: {_reason(r)}")
        data = r.json()
        return data if isinstance(data, list) else [data]  # satu titik -> dict, bukan list
    raise RuntimeError(f"Open-Meteo gagal setelah {max_retries} percobaan ({start}..{end}).")


def discover_cells(session, throttle, points, batch=50):
    """Sel grid model yang mencakup `points`: API mengembalikan koordinat sel
    terdekat untuk tiap titik, lalu yang sama digabung."""
    found = []
    for i in range(0, len(points), batch):
        found += [(resp["latitude"], resp["longitude"])
                  for resp in fetch(session, throttle, points[i:i + batch], START_DATE, START_DATE)]
    return dedupe_cells(found)


def total_weight(n_cells, start, end):
    """Perkiraan total bobot kuota untuk mengambil `n_cells` sel pada [start, end]."""
    return sum(
        request_weight(min(CELLS_PER_REQUEST, n_cells - i),
                       (date.fromisoformat(e) - date.fromisoformat(s)).days + 1)
        for s, e in date_chunks(start, end, DAYS_PER_REQUEST)
        for i in range(0, n_cells, CELLS_PER_REQUEST))


def fetch_range(session, throttle, cells, start, end):
    """Yield satu frame wide (semua sel) per potongan waktu, dari yang paling
    lama. Potongan yang sudah di-yield aman disimpan walau request berikutnya
    kena RateLimited."""
    for chunk_start, chunk_end in date_chunks(start, end, DAYS_PER_REQUEST):
        parts = []
        for i in range(0, len(cells), CELLS_PER_REQUEST):
            batch = cells[i:i + CELLS_PER_REQUEST]
            parts.append(responses_to_frame(fetch(session, throttle, batch, chunk_start, chunk_end),
                                            batch, VARIABLE))
        yield parts[0].join(parts[1:]) if len(parts) > 1 else parts[0]
