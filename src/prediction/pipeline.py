"""End-to-end forecast pipeline: raw BigQuery data -> forecast in cm.

Alur:
1. Tentukan model terbaik (`model_selection`) dan load bobotnya
   (`load_best_model`, dari script di root proyek).
2. Ambil `LOOKBACK` langkah (jam/hari) data terakhir dari `station_features`
   dan bangun fiturnya persis seperti `preprocessing`: isi NaN (median periode
   training), scale, kalender sin/cos, dan fitur hujan per stasiun dari
   `rainfall_hourly`.
3. Jalankan model per stasiun x horizon, dengan kolom fitur stasiun target
   -> prediksi dalam ruang scaled.
4. Inverse-transform ke satuan asli (cm).
5. (opsional) simpan hasil ke BigQuery `forecast_output`.
"""

import pandas as pd

from preprocessing.bigquery_io import authenticate, get_client

from .architectures import DEVICE
from .best_model import load_best_model
from .config import HORIZONS, LOOKBACK
from .data import load_recent_scaled
from .features import feature_cols_for, split_model_name
from .inference import TORCH_MODEL_NAMES, forecast_prophet, forecast_torch
from .scalers import inverse_transform
from .storage import save_forecast


def forecast_latest(station=None, horizons=None, client=None, write_bq=False):
    """Jalankan pipeline prediksi end-to-end dan kembalikan (forecast_df, model_name)."""
    if client is None:
        authenticate()
        client = get_client()

    horizons = horizons or HORIZONS

    models, model_name = load_best_model(client=client, station=station)
    architecture, use_rain = split_model_name(model_name)
    df_scaled, metadata, scalers = load_recent_scaled(client, lookback=LOOKBACK, use_rain=use_rain)

    generated_at = pd.Timestamp.now(tz="UTC").tz_localize(None)
    rows = []

    if architecture == "prophet":
        for target, model in models.items():
            # Regressor yang dipakai saat training (stasiun lain + hujan DAS target).
            regressors = list(model.extra_regressors)
            for h in horizons:
                as_of, forecast_time, pred_scaled = forecast_prophet(model, df_scaled, target, regressors, h)
                rows.append({
                    "model": model_name, "station": target, "horizon": h,
                    "as_of": as_of, "forecast_time": forecast_time,
                    "predicted_value_cm": inverse_transform(scalers[target], pred_scaled),
                    "generated_at": generated_at,
                })
    elif architecture in TORCH_MODEL_NAMES:
        for target, by_horizon in models.items():
            cols = feature_cols_for(metadata, target, use_rain)
            for h, model in by_horizon.items():
                if h not in horizons:
                    continue
                as_of, forecast_time, pred_scaled = forecast_torch(model, df_scaled[cols], LOOKBACK, h, DEVICE)
                rows.append({
                    "model": model_name, "station": target, "horizon": h,
                    "as_of": as_of, "forecast_time": forecast_time,
                    "predicted_value_cm": inverse_transform(scalers[target], pred_scaled),
                    "generated_at": generated_at,
                })
    else:
        raise ValueError(f"Model '{model_name}' tidak didukung oleh forecast_latest.")

    forecast_df = pd.DataFrame(rows)

    if write_bq:
        save_forecast(client, forecast_df)

    return forecast_df, model_name
