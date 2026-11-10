"""Per-station outlier flags (IQR, z-score, physical thresholds) and sensor-glitch cleaning.

Catatan: PHYSICAL_MIN_LEVEL menandai hampir seluruh Waduk Pluit (~93%)
karena muka air waduk memang di bawah -50 cm, jadi outlier_physical di
stasiun itu bukan indikasi data rusak. Flag di sini hanya untuk statistik;
yang benar-benar dibuang ditentukan oleh clean_glitches.
"""

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from .config import (
    DEFAULT_VALID_RANGE,
    IQR_K,
    PHYSICAL_MAX_JUMP,
    PHYSICAL_MIN_LEVEL,
    SPIKE_MAX_LEN,
    SPIKE_MAX_NEIGHBOR_GAP,
    SPIKE_MIN_DEV,
    VALID_RANGE,
    Z_THRESHOLD,
)

OUTLIER_COLS = ["outlier_iqr", "outlier_z", "outlier_physical", "outlier_any"]


def flag_outliers(df_long):
    """Tambah kolom OUTLIER_COLS ke long frame hasil resample_hourly."""
    df = df_long.copy()
    wl = df["water_level"]
    g = df.groupby("station_name")["water_level"]

    q1 = g.transform(lambda x: x.quantile(0.25))
    q3 = g.transform(lambda x: x.quantile(0.75))
    iqr = q3 - q1
    df["outlier_iqr"] = (wl < q1 - IQR_K * iqr) | (wl > q3 + IQR_K * iqr)

    zscore = (wl - g.transform("mean")) / g.transform("std")
    df["outlier_z"] = zscore.abs() > Z_THRESHOLD

    # Lonjakan antar jam berurutan (diff per stasiun).
    delta = g.diff()
    df["outlier_physical"] = (wl < PHYSICAL_MIN_LEVEL) | (delta.abs() > PHYSICAL_MAX_JUMP)

    df["outlier_any"] = df["outlier_iqr"] | df["outlier_z"] | df["outlier_physical"]
    return df


def spike_mask(series, min_dev=SPIKE_MIN_DEV, max_len=SPIKE_MAX_LEN, max_gap=SPIKE_MAX_NEIGHBOR_GAP):
    """True untuk nilai yang termasuk spike: run 1..`max_len` observasi valid
    berturut-turut yang semuanya menyimpang > `min_dev` dari nilai valid
    sebelum DAN sesudahnya (arah sama), di mana — relatif terhadap simpangan
    itu (dev) — kedua tetangga saling dekat (|sebelum - sesudah| < dev/2)
    dan masing-masing stabil terhadap tetangga berikutnya di luar run
    (selisih < dev/2). Syarat stabil inilah yang membedakan glitch (datar ->
    lompat -> datar lagi) dari puncak banjir asli, yang tetangganya sendiri
    sedang naik/surut. Tetangga harus berjarak <= `max_gap` jam dari run.

    NaN dilewati (tetangga = observasi valid terdekat), jadi glitch yang
    diapit gap tetap terdeteksi. Dua observasi pertama/terakhir tidak pernah
    ditandai karena tetangganya tidak lengkap."""
    valid = series.dropna()
    v = valid.to_numpy(dtype=float)
    hours = ((valid.index - valid.index[0]) / pd.Timedelta(hours=1)).to_numpy() if len(v) else v
    flagged = np.zeros(len(v), dtype=bool)

    for length in range(1, max_len + 1):
        # Run = v[s : s+length]; butuh dua tetangga di tiap sisi.
        starts = np.arange(2, len(v) - length - 1)
        if not len(starts):
            break
        runs = sliding_window_view(v, length)[starts]
        before, after = v[starts - 1], v[starts + length]
        before2, after2 = v[starts - 2], v[starts + length + 1]
        hi = np.maximum(before, after)[:, None]
        lo = np.minimum(before, after)[:, None]
        dev = np.maximum((runs - hi).min(axis=1), (lo - runs).min(axis=1))
        stable = (np.abs(before - before2) < dev / 2) & (np.abs(after - after2) < dev / 2)
        near = ((hours[starts] - hours[starts - 1] <= max_gap)
                & (hours[starts + length] - hours[starts + length - 1] <= max_gap))
        hit = (dev > min_dev) & (np.abs(before - after) < dev / 2) & stable & near
        for k in range(length):
            flagged[starts[hit] + k] = True

    return pd.Series(flagged, index=valid.index).reindex(series.index, fill_value=False)


def clean_glitches(df_wide, valid_range=VALID_RANGE, default_range=DEFAULT_VALID_RANGE):
    """Ganti glitch sensor di wide frame per jam (sebelum fill_gaps) dengan
    NaN: nilai di luar range stasiunnya, lalu spike (spike_mask). Range
    dibuang dulu supaya nilai seperti -1801 tidak dipakai sebagai tetangga.

    Return (df_bersih, DataFrame jumlah nilai yang dibuang per stasiun)."""
    df = df_wide.copy()
    stats = {}
    for station in df.columns:
        lo, hi = valid_range.get(station, default_range)
        out_of_range = (df[station] < lo) | (df[station] > hi)
        df[station] = df[station].mask(out_of_range)
        spikes = spike_mask(df[station])
        df[station] = df[station].mask(spikes)
        stats[station] = {"out_of_range": int(out_of_range.sum()), "spike": int(spikes.sum())}
    return df, pd.DataFrame(stats).T
