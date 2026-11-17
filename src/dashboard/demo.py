"""Data PALSU untuk melihat dashboard dan laporan PDF saat ada siaga: `make dashboard-demo`.

Skenario banjir kiriman Ciliwung: hujan lebat di hulu (Bogor) sejak ~10 jam lalu, Katulampa sekarang Siaga 1
(Awas) dan memuncak +1 jam, gelombangnya sampai Depok ~4 jam kemudian (lag dari `make travel-time`), jadi Depok naik
ke Siaga 2 dalam ~3 jam. Krukut Hulu Waspada, Pesanggrahan diprakirakan naik ke Waspada, pos lain Normal.

Tiap pos = satu kurva (naik seperti lonceng, surut eksponensial) yang dipakai untuk TMA aktual (t <= 0) dan
prakiraan (t > 0), jadi grafiknya menyambung. Tidak ada BigQuery: `install` mengganti pembaca snapshot dan
histori di app, dan laporan diberi tanda DATA DEMO di judul, keterangan dan kaki tiap halaman.
"""

import math
from datetime import datetime

import numpy as np
import pandas as pd

from . import app as app_module
from .data import HISTORY_STEPS, STATIONS, STEP_HOURS

# pos -> (TMA dasar cm, tinggi gelombang cm, jam puncak dari sekarang, lebar naik jam, surut jam)
SCENARIO = {
    "Bendung Katulampa": (50, 160, 1, 5, 6),     # Siaga 1 (Awas) sekarang, puncak 210 cm +1 jam
    "Pos Depok": (120, 170, 5, 6, 8),            # Waspada sekarang, Siaga 2 pada +3 jam, puncak +5 jam
    "Pos Krukut Hulu": (90, 85, 1, 4, 6),        # Waspada
    "Pos Pesanggrahan": (80, 90, 4, 5, 8),       # Normal, diprakirakan Waspada +3 jam
    "Pos Angke Hulu": (70, 6, 3, 5, 8),
    "Pos Cipinang Hulu": (60, 5, 2, 5, 8),
    "Pos Sunter Hulu": (50, 5, 2, 5, 8),
    "Waduk Pluit": (-85, 3, 2, 5, 8),
}
# sel hujan (lat, lon) -> hujan 24 jam terakhir (mm); hulu Ciliwung lebat
RAIN = {(-6.65, 106.85): 95, (-6.55, 106.85): 80, (-6.45, 106.80): 60, (-6.35, 106.80): 35,
        (-6.30, 106.75): 30, (-6.25, 106.70): 15, (-6.35, 106.90): 12, (-6.20, 106.85): 8}
RAIN_CELLS = {"Bendung Katulampa": [(-6.65, 106.85), (-6.55, 106.85)],
              "Pos Depok": [(-6.55, 106.85), (-6.45, 106.80)], "Pos Krukut Hulu": [(-6.35, 106.80)],
              "Pos Pesanggrahan": [(-6.30, 106.75)], "Pos Angke Hulu": [(-6.25, 106.70)],
              "Pos Cipinang Hulu": [(-6.35, 106.90)], "Pos Sunter Hulu": [(-6.35, 106.90)],
              "Waduk Pluit": [(-6.20, 106.85)]}
HORIZONS = (1, 3, 12)
MARK = "DATA DEMO, bukan pantauan nyata"


def level(station, t):
    """TMA (cm) pos pada jam `t` dari sekarang (negatif = lampau), dari kurva SCENARIO."""
    base, amp, peak, rise, fall = SCENARIO[station]
    shape = math.exp(-((t - peak) / rise) ** 2) if t <= peak else math.exp(-(t - peak) / fall)
    return base + amp * shape


def _cell(lat, lon):
    return f"rain_s{abs(lat):.4f}_e{lon:.4f}".replace(".", "_")


def _levels(as_of, steps):
    idx = pd.date_range(end=as_of, periods=steps, freq=f"{STEP_HOURS}h")
    hours = (idx - as_of) / pd.Timedelta(hours=1)
    rng = np.random.default_rng(0)
    # riak kecil + bulat ke 5 cm, supaya tidak terlihat seperti garis rumus (tapi tidak memicu "sudah naik")
    return pd.DataFrame({s: [round((level(s, t) + 1.5 * math.sin(t / 3.8) + rng.normal(0, 0.8)) / 5) * 5 for t in hours]
                         for s in SCENARIO}, index=idx)


def snapshot(as_of):
    """Snapshot berbentuk sama dengan data.load_snapshot: forecast, levels, rain, model."""
    forecast = pd.DataFrame([{"model": "gru", "station": s, "horizon": h, "as_of": as_of,
                              "forecast_time": as_of + pd.Timedelta(hours=h * STEP_HOURS),
                              "predicted_value_cm": round(level(s, h * STEP_HOURS), 1), "generated_at": as_of}
                             for s in SCENARIO for h in HORIZONS])
    rain_idx = pd.date_range(end=as_of, periods=HISTORY_STEPS * STEP_HOURS, freq="h")
    hours = (rain_idx - as_of) / pd.Timedelta(hours=1)
    # hujan 24 jam terakhir, terbanyak 6-10 jam lalu (memicu gelombang yang sekarang di Katulampa)
    weight = np.where(hours > -24, np.exp(-((hours + 8) / 4) ** 2), 0.0)
    rain = pd.DataFrame({_cell(*c): (weight / weight.sum() * mm).round(1) for c, mm in RAIN.items()}, index=rain_idx)
    model = {"best_model": "gru", "selection_metric": "nse", "stat": "median", "stat_value": 0.87,
             "rain_cells": {s: [_cell(*c) for c in cells] for s, cells in RAIN_CELLS.items()}}
    return {"forecast": forecast, "levels": _levels(as_of, HISTORY_STEPS), "rain": rain, "model": model}


def install():
    """Ganti pembaca BigQuery di app dengan data demo; as_of = jam penuh terakhir (WIB) saat dashboard dimulai."""
    as_of = pd.Timestamp(datetime.now(app_module.WIB).replace(tzinfo=None)).floor("h")
    snap = snapshot(as_of)
    app_module.load_snapshot = lambda force=False: snap
    app_module.load_history = lambda station, steps: _levels(as_of, steps)[[station]] if station in SCENARIO else None
    app_module.REPORT_CFG["demo"] = MARK
    app_module.SOURCES = f"{MARK.upper()} · {app_module.SOURCES}"
    app_module.DEMO = MARK.upper()
    app_module.app.title = "Flood Forecast · DEMO"
    missing = set(STATIONS) - set(SCENARIO)
    return as_of, missing
