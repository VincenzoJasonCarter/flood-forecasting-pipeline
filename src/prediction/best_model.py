"""Pick the best model (`model_selection`) and load its trained weights from BigQuery.

- Prophet        -> satu model per stasiun (horizon tidak relevan).
- LSTM/GRU       -> satu model PyTorch per (stasiun, horizon) (strategi direct).
- TFT            -> satu model PyTorch MIMO per stasiun yang memprediksi semua
                    HORIZONS sekaligus; baris bobotnya punya horizon = NULL.
                    Bobot direct lama (horizon terisi) tetap bisa dimuat.
  Jumlah fitur input per stasiun diambil dari metadata (fitur hujan per DAS).
- Akhiran "_norain" (mis. "lstm_norain") = varian ablation tanpa fitur hujan.
"""

import io
import logging
import pickle

import pandas as pd
import torch

from bq import run_query, scalar_param

from .architectures import DEVICE, TORCH_ARCHITECTURES, HorizonOutput
from .config import HORIZONS, MODEL_SELECTION_TABLE, weights_table
from .data import load_metadata
from .features import feature_cols_for, split_model_name

logger = logging.getLogger(__name__)


def get_best_model_name(client):
    row = run_query(client, "prediction/model_selection_latest", table=MODEL_SELECTION_TABLE)
    if row.empty:
        raise RuntimeError(
            f"{MODEL_SELECTION_TABLE} kosong — belum ada hasil model selection tersimpan."
        )
    best = row.iloc[0]
    # tabel baru menyimpan median_value, tabel lama mean_value; nilainya hanya untuk log
    stat = next((c for c in ("median_value", "mean_value") if c in best.index), None)
    logger.info("Best model: '%s' (%s %s=%s)", best["best_model"], best["selection_metric"],
                stat or "value", best[stat] if stat else "?")
    return best["best_model"]


def load_prophet_models(client, model_name="prophet", station=None):
    table_id = weights_table(model_name)
    rows = run_query(client, "prediction/prophet_weights", table=table_id,
                     params=[scalar_param("station", "STRING", station)])
    if rows.empty:
        raise RuntimeError(f"Tidak ada bobot di {table_id} (station={station!r}).")

    models = {}
    for _, row in rows.iterrows():
        models[row["station"]] = pickle.loads(row["weights"])
    return models


def load_torch_models(client, model_name, station=None, horizon=None):
    architecture, use_rain = split_model_name(model_name)
    metadata = load_metadata(client)
    build_model = TORCH_ARCHITECTURES[architecture]

    table_id = weights_table(model_name)
    rows = run_query(client, "prediction/torch_weights", table=table_id,
                     params=[scalar_param("station", "STRING", station),
                             scalar_param("horizon", "INT64", horizon)])
    if rows.empty:
        raise RuntimeError(f"Tidak ada bobot di {table_id} (station={station!r}, horizon={horizon!r}).")

    models = {}
    for _, row in rows.iterrows():
        station = row["station"]
        n_features = len(feature_cols_for(metadata, station, use_rain))
        mimo = pd.isna(row["horizon"])   # NULL = satu model MIMO untuk semua HORIZONS
        model = build_model(n_features, n_outputs=len(HORIZONS) if mimo else 1).to(DEVICE)
        try:
            model.load_state_dict(torch.load(io.BytesIO(row["weights"]), map_location=DEVICE))
        except RuntimeError as exc:
            if not mimo:
                raise
            raise RuntimeError(
                f"Bobot MIMO {model_name} ({station}) tidak cocok dengan HORIZONS={HORIZONS} "
                f"di config/prediction.yaml; horizon saat training harus sama (dan urutannya)."
            ) from exc
        model.eval()

        by_horizon = models.setdefault(station, {})
        if mimo:
            for j, h in enumerate(HORIZONS):
                if horizon is None or h == horizon:
                    by_horizon[h] = HorizonOutput(model, j).eval()
        else:
            by_horizon[int(row["horizon"])] = model

    if not any(models.values()):
        raise RuntimeError(f"Tidak ada model {model_name} untuk horizon={horizon!r} (HORIZONS={HORIZONS}).")
    return models


def load_best_model(client=None, station=None, horizon=None):
    """Muat bobot model terbaik (menurut model_selection) dari BigQuery.

    Return: (models, model_name)
    - arsitektur prophet: models = {station: Prophet model}
    - lainnya: models = {station: {horizon: nn.Module (eval mode)}}
    """
    if client is None:
        from .client import authenticate, get_client
        authenticate()
        client = get_client()

    model_name = get_best_model_name(client)
    architecture, _ = split_model_name(model_name)

    if architecture == "prophet":
        if horizon is not None:
            logger.info("Prophet tidak per-horizon; parameter --horizon diabaikan.")
        models = load_prophet_models(client, model_name, station=station)
    elif architecture in TORCH_ARCHITECTURES:
        models = load_torch_models(client, model_name, station=station, horizon=horizon)
    else:
        raise ValueError(f"Model '{model_name}' tidak dikenal oleh load_best_model.")

    return models, model_name
