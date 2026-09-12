"""Pick the best model (`model_selection`) and load its trained weights from BigQuery.

- Prophet        -> satu model per stasiun (horizon tidak relevan).
- LSTM/GRU/TFT   -> satu model PyTorch per (stasiun, horizon).
"""

import io
import json
import pickle

import torch
from google.cloud import bigquery

from .architectures import DEVICE, TORCH_ARCHITECTURES
from .config import METADATA_TABLE, MODEL_SELECTION_TABLE, weights_table


def get_best_model_name(client):
    row = client.query(f"""
        SELECT best_model, selection_metric, mean_value
        FROM `{MODEL_SELECTION_TABLE}`
        ORDER BY saved_at DESC
        LIMIT 1
    """).to_dataframe()
    if row.empty:
        raise RuntimeError(
            f"{MODEL_SELECTION_TABLE} kosong — belum ada hasil model selection tersimpan."
        )
    best = row.iloc[0]
    print(f"Best model: '{best['best_model']}' ({best['selection_metric']}={best['mean_value']:.4f})")
    return best["best_model"]


def get_n_features(client):
    row = client.query(f"""
        SELECT payload
        FROM `{METADATA_TABLE}`
        ORDER BY saved_at DESC
        LIMIT 1
    """).to_dataframe().iloc[0]
    metadata = json.loads(row["payload"])
    return len(metadata["feature_cols"])


def load_prophet_models(client, station=None):
    table_id = weights_table("prophet")
    query = f"SELECT station, weights FROM `{table_id}`"
    params = []
    if station is not None:
        query += " WHERE station = @station"
        params.append(bigquery.ScalarQueryParameter("station", "STRING", station))
    rows = client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
    if rows.empty:
        raise RuntimeError(f"Tidak ada bobot di {table_id} (station={station!r}).")

    models = {}
    for _, row in rows.iterrows():
        models[row["station"]] = pickle.loads(row["weights"])
    return models


def load_torch_models(client, model_name, station=None, horizon=None):
    n_features = get_n_features(client)
    build_model = TORCH_ARCHITECTURES[model_name]

    table_id = weights_table(model_name)
    query = f"SELECT station, horizon, weights FROM `{table_id}`"
    clauses, params = [], []
    if station is not None:
        clauses.append("station = @station")
        params.append(bigquery.ScalarQueryParameter("station", "STRING", station))
    if horizon is not None:
        clauses.append("horizon = @horizon")
        params.append(bigquery.ScalarQueryParameter("horizon", "INT64", horizon))
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    rows = client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
    if rows.empty:
        raise RuntimeError(f"Tidak ada bobot di {table_id} (station={station!r}, horizon={horizon!r}).")

    models = {}
    for _, row in rows.iterrows():
        model = build_model(n_features).to(DEVICE)
        model.load_state_dict(torch.load(io.BytesIO(row["weights"]), map_location=DEVICE))
        model.eval()
        models.setdefault(row["station"], {})[int(row["horizon"])] = model
    return models


def load_best_model(client=None, station=None, horizon=None):
    """Muat bobot model terbaik (menurut model_selection) dari BigQuery.

    Return: (models, model_name)
    - model_name == "prophet": models = {station: Prophet model}
    - lainnya: models = {station: {horizon: nn.Module (eval mode)}}
    """
    if client is None:
        from preprocessing.bigquery_io import authenticate, get_client
        authenticate()
        client = get_client()

    model_name = get_best_model_name(client)

    if model_name == "prophet":
        if horizon is not None:
            print("  [info] Prophet tidak per-horizon; parameter --horizon diabaikan.")
        models = load_prophet_models(client, station=station)
    elif model_name in TORCH_ARCHITECTURES:
        models = load_torch_models(client, model_name, station=station, horizon=horizon)
    else:
        raise ValueError(f"Model '{model_name}' tidak dikenal oleh load_best_model.")

    return models, model_name
