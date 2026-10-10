"""Run inference for the loaded best model against the most recent data."""

import torch

from .config import TIME_STEP
from .windowing import prophet_frame, torch_window

TORCH_MODEL_NAMES = {"lstm", "gru", "tft"}


def forecast_torch(model, df_scaled, lookback, horizon, device):
    x = torch_window(df_scaled, lookback).to(device)
    with torch.no_grad():
        pred_scaled = model(x).item()
    as_of = df_scaled.index[-1]
    forecast_time = as_of + horizon * TIME_STEP
    return as_of, forecast_time, pred_scaled


def forecast_prophet(model, df_scaled, target_station, other_stations, horizon):
    """Direct forecasting: regressor terkini (t) -> prediksi target di t+h,
    sesuai strategi direct forecasting yang dipakai saat training Prophet.
    """
    df_p = prophet_frame(df_scaled, target_station, other_stations)
    as_of = df_p["ds"].iloc[0]

    df_shifted = df_p.copy()
    df_shifted["ds"] = df_shifted["ds"] + horizon * TIME_STEP
    forecast = model.predict(df_shifted)

    pred_scaled = float(forecast["yhat"].iloc[0])
    forecast_time = as_of + horizon * TIME_STEP
    return as_of, forecast_time, pred_scaled
