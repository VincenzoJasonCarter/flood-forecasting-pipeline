"""Pure helpers: grid cells, column naming, API responses -> wide frame, merging."""

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import COLUMN_PREFIX


def candidate_points(lat_min, lat_max, lon_min, lon_max, step):
    """Titik uji (lat, lon) di dalam kotak, tiap `step` derajat (ujung inklusif)."""
    lats = np.round(np.arange(lat_min, lat_max + 1e-9, step), 4)
    lons = np.round(np.arange(lon_min, lon_max + 1e-9, step), 4)
    return [(float(lat), float(lon)) for lat in lats for lon in lons]


def dedupe_cells(coords):
    """Koordinat sel grid unik (dibulatkan 4 desimal), terurut."""
    return sorted({(round(lat, 4), round(lon, 4)) for lat, lon in coords})


def cell_column(lat, lon):
    """Nama kolom (aman untuk BigQuery) dari koordinat sel, mis. rain_s6_6432_e106_7899."""
    ns = "s" if lat < 0 else "n"
    ew = "w" if lon < 0 else "e"
    return f"{COLUMN_PREFIX}{ns}{abs(lat):.4f}_{ew}{abs(lon):.4f}".replace(".", "_")


_CELL_RE = re.compile(rf"^{COLUMN_PREFIX}([ns])(\d+)_(\d+)_([ew])(\d+)_(\d+)$")


def parse_cell_column(name):
    """Kebalikan cell_column: rain_s6_6432_e106_7899 -> (-6.6432, 106.7899)."""
    m = _CELL_RE.match(name)
    if m is None:
        raise ValueError(f"Bukan nama kolom sel hujan: {name!r}")
    ns, lat_int, lat_dec, ew, lon_int, lon_dec = m.groups()
    lat = float(f"{lat_int}.{lat_dec}") * (-1 if ns == "s" else 1)
    lon = float(f"{lon_int}.{lon_dec}") * (-1 if ew == "w" else 1)
    return lat, lon


def select_top_cells(ranking, top):
    """Gabungan `top` sel teratas tiap stasiun dari tabel ranking
    (kolom station, cell, corr) -> koordinat sel unik, terurut."""
    best = (ranking.dropna(subset=["corr"])
            .sort_values("corr", ascending=False)
            .groupby("station", sort=False)
            .head(top))
    return sorted({parse_cell_column(c) for c in best["cell"]})


def date_chunks(start, end, days):
    """Pecah rentang tanggal inklusif [start, end] jadi potongan maksimal `days` hari."""
    cur, last = date.fromisoformat(start), date.fromisoformat(end)
    chunks = []
    while cur <= last:
        stop = min(cur + timedelta(days=days - 1), last)
        chunks.append((cur.isoformat(), stop.isoformat()))
        cur = stop + timedelta(days=1)
    return chunks


def responses_to_frame(responses, cells, variable):
    """Respons Open-Meteo (satu per sel, urutan sama dengan `cells`) -> frame
    wide: index datetime (jam lokal, naive), satu kolom per sel."""
    if len(responses) != len(cells):
        raise ValueError(f"{len(responses)} respons untuk {len(cells)} sel")
    columns = {}
    index = None
    for (lat, lon), resp in zip(cells, responses):
        hourly = resp["hourly"]
        idx = pd.DatetimeIndex(pd.to_datetime(hourly["time"]), name="datetime")
        index = idx if index is None else index
        columns[cell_column(lat, lon)] = pd.Series(hourly[variable], index=idx, dtype="float64")
    return pd.DataFrame(columns, index=index)


def drop_future(df, now):
    """Buang baris setelah jam `now`: API ikut mengembalikan prakiraan untuk
    jam-jam yang belum terjadi, bukan hujan yang sudah turun."""
    return df[df.index <= pd.Timestamp(now).floor("h")]


def merge_incremental(existing, new, start):
    """Gabungkan output lama dengan hasil ambil ulang: baris sejak `start`
    diganti hasil baru (nilai model untuk jam-jam terakhir bisa direvisi oleh
    run berikutnya). Kolom mengikuti `existing`."""
    cut = pd.Timestamp(start)
    extra = [c for c in new.columns if c not in existing.columns]
    if extra:
        print(f"Peringatan: kolom tidak ada di output lama, dilewati: {extra}")
    new = new.reindex(columns=existing.columns)
    return pd.concat([existing[existing.index < cut], new[new.index >= cut]])
