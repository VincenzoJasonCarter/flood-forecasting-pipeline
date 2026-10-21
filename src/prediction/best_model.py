"""Pick the best model (`model_selection`) and load its trained weights from BigQuery.

- Prophet        -> satu model per stasiun (horizon tidak relevan).
- LSTM/GRU/TFT   -> satu model PyTorch per (stasiun, horizon), dengan jumlah
                    fitur input per stasiun dari metadata (fitur hujan per DAS).
- Akhiran "_norain" (mis. "lstm_norain") = varian ablation tanpa fitur hujan.
"""

import io
import logging
import pickle

import torch

from bq import run_query, scalar_param

from .architectures import DEVICE, TORCH_ARCHITECTURES
from .config import MODEL_SELECTION_TABLE, weights_table
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
    logger.info("Best model: '%s' (%s=%.4f)", best["best_model"], best["selection_metric"], best["mean_value"])
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
        n_features = len(feature_cols_for(metadata, row["station"], use_rain))
        model = build_model(n_features).to(DEVICE)
        model.load_state_dict(torch.load(io.BytesIO(row["weights"]), map_location=DEVICE))
        model.eval()
        models.setdefault(row["station"], {})[int(row["horizon"])] = model
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
