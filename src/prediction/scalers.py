"""Load the per-station MinMaxScalers saved by the preprocessing pipeline."""

import pickle

from .config import SCALERS_TABLE


def load_scalers(client):
    rows = client.query(f"SELECT station, scaler_blob FROM `{SCALERS_TABLE}`").to_dataframe()
    if rows.empty:
        raise RuntimeError(f"{SCALERS_TABLE} kosong — jalankan `python -m preprocessing` dulu.")
    return {row["station"]: pickle.loads(row["scaler_blob"]) for _, row in rows.iterrows()}


def inverse_transform(scaler, value):
    return float(scaler.inverse_transform([[value]])[0, 0])
