"""Per-station outlier flags (IQR, z-score, physical thresholds) and isolated-spike cleaning.

Catatan: PHYSICAL_MIN_LEVEL menandai hampir seluruh Waduk Pluit (~93%)
karena muka air waduk memang di bawah -50 cm, jadi outlier_physical di
stasiun itu bukan indikasi data rusak.
"""

from .config import IQR_K, PHYSICAL_MAX_JUMP, PHYSICAL_MIN_LEVEL, SPIKE_INTERP_LIMIT, Z_THRESHOLD

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


def _isolated(flag):
    return flag & ~flag.shift(1, fill_value=False) & ~flag.shift(-1, fill_value=False)


def clean_isolated_spikes(df_flagged):
    """Ganti outlier_physical yang terisolasi (1 jam, tetangganya normal)
    dengan NaN, lalu interpolasi linear per stasiun (limit SPIKE_INTERP_LIMIT)."""
    df = df_flagged.copy()
    isolated = df.groupby("station_name")["outlier_physical"].transform(_isolated)
    df["water_level"] = df["water_level"].mask(isolated)
    df["water_level"] = (df
                         .groupby("station_name")["water_level"]
                         .transform(lambda x: x.interpolate(limit=SPIKE_INTERP_LIMIT)))
    return df
