"""Per-station MinMax scaling and BigQuery-safe column naming."""

import re

from sklearn.preprocessing import MinMaxScaler


def fit_scalers(df_train_raw, station_cols):
    scalers = {}
    for station in station_cols:
        scaler = MinMaxScaler(feature_range=(0, 1))
        valid_vals = df_train_raw[station].dropna().values.reshape(-1, 1)
        scaler.fit(valid_vals)
        scalers[station] = scaler
        print(f"  [{station}] min={scaler.data_min_[0]:.1f} cm, max={scaler.data_max_[0]:.1f} cm")
    return scalers


def apply_scalers(df, scalers, station_cols):
    df = df.copy()
    for station in station_cols:
        mask = df[station].notna()
        df.loc[mask, station] = scalers[station].transform(
            df.loc[mask, station].values.reshape(-1, 1)
        ).flatten()
    return df


def to_bq_column(name):
    """Nama kolom BigQuery harus alfanumerik + underscore."""
    return re.sub(r"[^0-9a-zA-Z_]", "_", name)


def make_bq_frame(df, split, column_map):
    out = df.rename(columns=column_map).reset_index()
    out["split"] = split
    return out
