"""Load the per-station MinMaxScalers saved by the preprocessing pipeline."""

import pickle

from bq import run_query

from .config import SCALERS_TABLE


def load_scalers(client):
    rows = run_query(client, "prediction/scalers", table=SCALERS_TABLE)
    if rows.empty:
        raise RuntimeError(f"{SCALERS_TABLE} kosong — jalankan `python -m preprocessing` dulu.")
    return {row["station"]: pickle.loads(row["scaler_blob"]) for _, row in rows.iterrows()}


def inverse_transform(scaler, value):
    return float(scaler.inverse_transform([[value]])[0, 0])
