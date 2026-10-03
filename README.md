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
│   ├── raw_preprocessing.yaml # API endpoint + BigQuery table names used by src/raw_preprocessing
│   ├── preprocessing.yaml   # BigQuery project/dataset/table names used by src/preprocessing
│   └── prediction.yaml      # BigQuery project/dataset/table names used by src/prediction
├── docs/
│   └── architecture.md      # module-level call flow, pure vs. I/O boundaries
├── tests/                   # unit tests for pure logic (no BigQuery access)
└── src/
    ├── settings.py          # loads a module's YAML from config/
    ├── raw_preprocessing/   # API crawl -> station_features_{hourly,daily} (water level + calendar features)
    ├── preprocessing/       # one-time setup: station_features -> train/val/test, scalers, metadata
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

`config/raw_preprocessing.yaml`, `config/preprocessing.yaml` and
`config/prediction.yaml` each declare their own `project`, `dataset`,
`location`, and the BigQuery table names they read or write. They're separate files because preprocessing and prediction are
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

Build `station_features_hourly` or `station_features_daily` from the
sisteminformasibanjir API (crawls one request per day, so a full history
takes a while). `granularity` in `config/raw_preprocessing.yaml` picks the
default (`daily` = daily max per station, `hourly` = the hourly grid);
`--granularity` overrides it per run. The API token is read
from the `SIBANJIR_TOKEN` env var — put it in `.env` (copy `.env.example`)
and the Makefile passes it through:

```
make raw-preprocess                               # -> artifacts/station_features_daily.parquet
make raw-preprocess ARGS="--granularity hourly"   # -> artifacts/station_features_hourly.parquet
make raw-preprocess ARGS="--end 2026-08-25"
make raw-preprocess-bq                            # also writes tables.station_features_<granularity> (WRITE_TRUNCATE)
```

Then preprocess that table for modelling. `granularity` in
`config/preprocessing.yaml` picks which table set is read and written
(`station_features_<g>` -> `preprocessed_data_<g>`,
`preprocessing_metadata_<g>`, `preprocessing_scalers_<g>`):

```
make preprocess                                   # uses granularity from config
make preprocess ARGS="--granularity hourly"
```

None of these touch the unsuffixed tables (`station_features`,
`preprocessing_metadata`, `preprocessing_scalers`) that `prediction` reads for
the currently deployed models — point `config/prediction.yaml` at the
`_hourly`/`_daily` tables once a model for that granularity is trained. Run
`make help` for every target.

Run the test suite (unit tests only, no BigQuery access needed):

```
uv run pytest
```

## How it fits together

0. `raw_preprocessing` crawls hourly water-level reports from the
   sisteminformasibanjir API, resamples them to a continuous hourly grid per
   station, fills short gaps (≤ 6 h per fill step), optionally aggregates to
   the daily maximum per station (`granularity`), adds calendar features,
   and writes `station_features_hourly` / `station_features_daily`. Outlier flags are computed for reporting;
   spike removal is off by default to match the data models were trained on.
1. `preprocessing` reads `station_features_<granularity>`, fills NaNs with
   per-station hourly medians (an overall median for daily data), scales each
   station with its own `MinMaxScaler`, and writes
   `preprocessed_data_<granularity>`, `preprocessing_metadata_<granularity>`,
   and `preprocessing_scalers_<granularity>` to BigQuery.
2. Training (external to this repo) fits Prophet/LSTM/GRU/TFT on that data
   and writes bobot (weights) to `{model}_weights` plus validation/test
   metrics, and a model-selection step writes the winner to
   `model_selection`.
3. `prediction` reads `model_selection` to pick the winning model, loads its
   weights, pulls the latest data from the tables in `config/prediction.yaml`
   (currently the unsuffixed hourly ones), reapplies the same
   preprocessing/scaling, runs inference, and inverse-transforms the result
   back to cm.

See [docs/architecture.md](docs/architecture.md) for the module-level call
flow behind each step.
