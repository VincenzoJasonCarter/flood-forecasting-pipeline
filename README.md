# Flood Forecasting Pipeline

End-to-end forecast serving for river water-level stations. Given a model
already trained and selected as "best" (Prophet, LSTM, GRU, or TFT — weights
and selection results already live in BigQuery), this pipeline pulls the
freshest raw sensor data, preprocesses it the same way the training data was
prepared, runs inference, and returns the forecast in real units (cm).

Training is not part of this repo — the four candidate models don't need
retraining, so only the serving path (preprocessing + inference) is kept
here.

## Project layout

```
.
├── main.py                  # production entrypoint (runs the forecast pipeline)
├── pyproject.toml / uv.lock # dependencies
├── config/
│   ├── preprocessing.yaml   # BigQuery project/dataset/table names used by src/preprocessing
│   └── prediction.yaml      # BigQuery project/dataset/table names used by src/prediction
└── src/
    ├── settings.py          # loads a module's YAML from config/
    ├── preprocessing/       # one-time setup: raw data -> train/val/test, scalers, metadata
    ├── prediction/          # forecast pipeline: best model + latest data -> forecast (cm)
    ├── load_best_model.py   # CLI: inspect/load the current best model's weights
    └── predict.py           # CLI: run the full forecast pipeline
```

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.10–3.12 (uv will fetch
a matching interpreter automatically if you don't have one).

```
uv sync
```

This creates `.venv/` with every dependency pinned exactly as resolved in
`uv.lock` — no manual environment setup needed on a new machine.

### Google Cloud credentials

The pipeline talks to BigQuery directly (`google.cloud.bigquery`), so it
needs credentials in the environment it runs in — Application Default
Credentials:

```
gcloud auth application-default login
```

or, in a deployed/production environment, a service account key via
`GOOGLE_APPLICATION_CREDENTIALS`. (`authenticate()` in `preprocessing` is a
no-op outside Google Colab — it only handles the Colab-specific auth flow.)

## Configuration

`config/preprocessing.yaml` and `config/prediction.yaml` each declare their
own `project`, `dataset`, `location`, and the BigQuery table names they read
or write. They're separate files because preprocessing and prediction are
independently runnable — pointing either one at a different project/dataset
(e.g. a staging environment) doesn't require touching the other.

## Usage

Run the full forecast pipeline (latest data → forecast, in cm):

```
uv run python main.py
uv run python main.py --station "Bendung Katulampa" --horizon 1 3
uv run python main.py --write-bq        # also persist to tables.forecast_output
uv run python main.py --csv forecast.csv
```

Inspect which model is currently "best" and load its weights without running
a forecast (useful for debugging):

```
uv run python src/load_best_model.py
uv run python src/load_best_model.py --station "Bendung Katulampa" --horizon 3
```

Re-run preprocessing (only needed if bootstrapping a fresh BigQuery
project/dataset — the current one is already populated):

```
cd src && uv run python -m preprocessing
```

## How it fits together

1. `preprocessing` (one-time) reads raw `station_features`, fills NaNs with
   per-station hourly medians, scales each station with its own
   `MinMaxScaler`, and writes `preprocessed_data`, `preprocessing_metadata`,
   and `preprocessing_scalers` to BigQuery.
2. Training (external to this repo) fits Prophet/LSTM/GRU/TFT on that data
   and writes bobot (weights) to `{model}_weights` plus validation/test
   metrics, and a model-selection step writes the winner to
   `model_selection`.
3. `prediction` reads `model_selection` to pick the winning model, loads its
   weights, pulls the latest raw data, reapplies the same
   preprocessing/scaling, runs inference, and inverse-transforms the result
   back to cm.
