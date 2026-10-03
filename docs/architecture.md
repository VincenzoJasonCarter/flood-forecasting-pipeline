# Architecture

Module-level detail behind the [README](../README.md) overview — what calls
what, and which parts are pure functions vs. BigQuery I/O.

## `src/raw_preprocessing` (builds `station_features_{hourly,daily}`)

Entry point: `make raw-preprocess` / `python -m raw_preprocessing` -> `pipeline.run()`. Module form of
the non-EDA cells of `EDA_Preprocess_Flood.ipynb`.

```
crawler.crawl_range                 (I/O: sisteminformasibanjir API, 1 request/day)
        |
parsing.flatten_records             (pure: nested JSON -> typed long frame, dedup)
        |
resampling.resample_hourly          (pure: hourly mean per station)
        |
outliers.flag_outliers              (pure: IQR / z-score / physical flags)
outliers.clean_isolated_spikes      (pure, off by default: CLEAN_ISOLATED_SPIKES)
        |
resampling.to_wide                  (pure: pivot -> one column per station, hourly grid)
        |
gaps.fill_gaps                      (pure: time interpolate -> ffill -> bfill, limit 6 h)
        |
resampling.to_daily_max             (pure, granularity daily only: hourly grid -> daily max)
        |
features.add_calendar_features      (pure: CALENDAR_COLS, Indonesian holidays)
        |
storage.save_parquet / save_station_features   (I/O: local parquet; BigQuery only with --write-bq)
```

Everything except `crawler` and `storage` is pure and unit-tested
(`tests/raw_preprocessing/`). `CALENDAR_COLS` is defined here as the
producer and duplicated in `preprocessing.config` as the consumer; a test
asserts the two lists stay identical. With `granularity: daily`, `hour` is
always 0 — it's kept only so the column schema matches `station_features`.

## `src/preprocessing` (one-time bootstrap)

Entry point: `make preprocess` / `python -m preprocessing` -> `pipeline.run()`.
`granularity` (config or `--granularity`) selects the table set via
`config.table_id(name, granularity)`.

```
bigquery_io.load_station_features   (I/O: reads station_features_<granularity>)
        |
splitting.get_station_cols / split_data      (pure: train/val/test by ratio)
        |
imputation.compute_hourly_medians / fill_nan_hourly_median   (pure)
        |
scaling.fit_scalers / apply_scalers / to_bq_column           (pure)
        |
storage.save_preprocessed_data / save_metadata / save_scalers  (I/O: writes *_<granularity>)
```

`splitting`, `imputation`, and `scaling` have no BigQuery dependency and are
unit-tested directly (see `tests/preprocessing/`). `bigquery_io` and
`storage` are I/O boundaries and are not unit-tested — they're exercised by
actually running the pipeline against a real project/dataset.

## `src/prediction` (per-request forecast)

Entry point: `predict.main()` -> `pipeline.forecast_latest()`.

```
best_model.load_best_model     (I/O: reads model_selection + {model}_weights)
data.load_recent_scaled        (I/O: reads prediction.yaml's station_features,
                                 reapplies imputation/scaling from preprocessing)
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
one-time bootstrap pipeline changes later. It reuses
`preprocessing.bigquery_io.load_station_features` but passes its own table
from `config/prediction.yaml`, so switching `preprocessing`'s granularity
never changes what the deployed model receives.

## Config loading

`src/settings.py` reads `config/{name}.yaml` relative to the repo root at
import time. `raw_preprocessing/config.py`, `preprocessing/config.py` and
`prediction/config.py` each call `load_config` once at module import and
derive their table-path constants from it — so importing any of these
packages requires the corresponding YAML file
to exist, but does not require GCP credentials or network access.

## Testing

```
uv run pytest
```

`pyproject.toml` sets `pythonpath = ["src"]` so tests import packages the
same way `main.py` does (`sys.path` pointed at `src/`), without needing a
package install. Tests are limited to pure-logic modules; nothing talks to
BigQuery.
