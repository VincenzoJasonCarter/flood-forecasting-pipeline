"""Model features built on top of station_features: cyclical calendar encoding
and per-station catchment rainfall accumulations.

Dipakai oleh pipeline preprocessing (training) dan package prediction
(serving), supaya fitur keduanya dihitung oleh kode yang sama.
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

# Kolom kalender siklik -> periodenya. Encoding sin/cos membuat jam 23 dan
# jam 0 (Desember dan Januari, Minggu dan Senin) berdekatan, dan skalanya
# [-1, 1] seperti fitur lain (nilai mentah month 1..12 / hour 0..23 tidak).
CYCLICAL_PERIODS = {"hour": 24, "month": 12, "day_of_week": 7}
BINARY_CALENDAR_COLS = ["is_weekend", "is_holiday", "is_rainy_season"]
CALENDAR_FEATURE_COLS = ([f"{col}_{fn}" for col in CYCLICAL_PERIODS for fn in ("sin", "cos")]
                         + BINARY_CALENDAR_COLS)


def encode_calendar(df):
    """Ganti hour/month/day_of_week dengan pasangan sin/cos; kolom biner tetap."""
    out = df.copy()
    for col, period in CYCLICAL_PERIODS.items():
        angle = 2 * np.pi * out[col].astype(float) / period
        out[f"{col}_sin"] = np.sin(angle)
        out[f"{col}_cos"] = np.cos(angle)
    others = [c for c in out.columns if c not in CYCLICAL_PERIODS and c not in CALENDAR_FEATURE_COLS]
    return out[others + CALENDAR_FEATURE_COLS]


def top_cells_by_station(ranking, top):
    """{station: [kolom sel]}: `top` sel dengan korelasi tertinggi tiap
    stasiun dari ranking `rainfall.analysis` (kolom station, cell, corr)."""
    ranked = ranking.dropna(subset=["corr"]).sort_values("corr", ascending=False)
    return {station: grp["cell"].head(top).tolist() for station, grp in ranked.groupby("station", sort=False)}


def rain_feature_col(station_bq, hours):
    return f"rain_{station_bq}_{hours}h"


def rain_features(rain, cells_by_station, accum_hours, column_map, index):
    """Fitur hujan tiap stasiun pada grid per jam `index`: rata-rata hujan
    sel-sel stasiun itu, dijumlah selama k jam terakhir (termasuk jam ini)
    untuk tiap k di `accum_hours`.

    Hujan di timestamp t adalah hujan selama (t-1 jam, t], jadi fitur di baris
    t hanya memakai hujan yang sudah turun. Jam tanpa data hujan dianggap 0.

    Return (features, {station: [kolom fitur]})."""
    columns, cols_by_station = {}, {}
    for station, cells in cells_by_station.items():
        missing = [c for c in cells if c not in rain.columns]
        if missing:
            raise KeyError(f"Sel hujan {missing} untuk {station!r} tidak ada di data hujan "
                           f"(ambil dengan `make rainfall-bq` / TOP yang cukup).")
        catchment = rain[cells].mean(axis=1).reindex(index)
        n_missing = int(catchment.isna().sum())
        if n_missing:
            print(f"  [{station}] {n_missing:,} jam tanpa data hujan diisi 0")
        catchment = catchment.fillna(0.0)
        cols_by_station[station] = []
        for hours in accum_hours:
            name = rain_feature_col(column_map[station], hours)
            columns[name] = catchment.rolling(hours, min_periods=1).sum()
            cols_by_station[station].append(name)
    return pd.DataFrame(columns, index=index), cols_by_station


def fit_rain_scalers(features, cols):
    """MinMaxScaler per kolom hujan, di-fit pada log1p(mm): hujan sangat
    miring (kebanyakan 0, sedikit nilai ekstrem). Fit di periode train saja."""
    return {c: MinMaxScaler().fit(np.log1p(features[[c]].to_numpy())) for c in cols}


def apply_rain_scalers(features, scalers, cols):
    out = features.copy()
    for c in cols:
        out[c] = scalers[c].transform(np.log1p(out[[c]].to_numpy())).ravel()
    return out
