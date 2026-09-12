# Architecture

Module-level detail behind the [README](../README.md) overview — what calls
what, and which parts are pure functions vs. BigQuery I/O.

## `src/preprocessing` (one-time bootstrap)

Entry point: `python -m preprocessing` -> `pipeline.run()`.

```
bigquery_io.load_station_features   (I/O: reads station_features)
        |
splitting.get_station_cols / split_data      (pure: train/val/test by ratio)
        |
imputation.compute_hourly_medians / fill_nan_hourly_median   (pure)
        |
scaling.fit_scalers / apply_scalers / to_bq_column           (pure)
        |
storage.save_preprocessed_data / save_metadata / save_scalers  (I/O: writes)
```

`splitting`, `imputation`, and `scaling` have no BigQuery dependency and are
unit-tested directly (see `tests/preprocessing/`). `bigquery_io` and
`storage` are I/O boundaries and are not unit-tested — they're exercised by
actually running the pipeline against a real project/dataset.

## `src/prediction` (per-request forecast)

Entry point: `predict.main()` -> `pipeline.forecast_latest()`.

```
best_model.load_best_model     (I/O: reads model_selection + {model}_weights)
data.load_recent_scaled        (I/O: reads station_features, reapplies
                                 imputation/scaling from preprocessing)
        |
windowing.torch_window / prophet_frame   (pure: shape data for inference)
        |
inference.forecast_torch / forecast_prophet   (runs the loaded model)
        |
scalers.inverse_transform      (pure: scaled prediction -> cm)
        |
storage.save_forecast          (I/O: optional, --write-bq)
```

`windowing` and `scalers.inverse_transform` are pure and unit-tested
(`tests/prediction/`). Note `data.load_recent_scaled` intentionally
duplicates the imputation/scaling logic from `preprocessing` rather than
importing it, so serving-time preprocessing stays reproducible even if the
one-time bootstrap pipeline changes later.

## Config loading

`src/settings.py` reads `config/{name}.yaml` relative to the repo root at
import time. `preprocessing/config.py` and `prediction/config.py` each call
`load_config` once at module import and derive their table-path constants
from it — so importing either package requires the corresponding YAML file
to exist, but does not require GCP credentials or network access.

## Testing

```
uv run pytest
```

`pyproject.toml` sets `pythonpath = ["src"]` so tests import packages the
same way `main.py` does (`sys.path` pointed at `src/`), without needing a
package install. Tests are limited to pure-logic modules; nothing talks to
BigQuery.
