"""Turn the most recent scaled data into model-ready inputs."""

import numpy as np
import torch


def torch_window(df_scaled, lookback):
    """(1, lookback, n_features) tensor dari `lookback` baris terakhir."""
    window = df_scaled.tail(lookback).values.astype(np.float32)
    if len(window) < lookback:
        raise RuntimeError(f"Butuh {lookback} baris data, hanya ada {len(window)}.")
    return torch.tensor(window).unsqueeze(0)


def prophet_frame(df_scaled, target_station, regressors):
    """Satu baris (waktu terkini) dalam format Prophet: ds + regressors.

    `y` diisi placeholder dari nilai target sendiri (tidak dipakai saat
    predict), sesuai skema training Prophet-nya.
    """
    latest = df_scaled.iloc[[-1]][[target_station] + list(regressors)].copy()
    return latest.reset_index().rename(columns={"datetime": "ds", target_station: "y"})
