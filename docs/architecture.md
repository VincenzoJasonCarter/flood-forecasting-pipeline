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

## `src/rainfall` (builds `rainfall_hourly`)

Entry point: `make rainfall` / `python -m rainfall` -> `pipeline.run()`.

```
frames.candidate_points             (pure: probe points over config grid bbox)
        |
client.discover_cells               (I/O: Open-Meteo snaps each point to its model cell;
                                     frames.dedupe_cells merges duplicates)
        |
client.fetch_range                  (I/O: time chunks x cell batches; RateLimited on HTTP 429)
frames.responses_to_frame           (pure: responses -> wide frame, one rain_<lat>_<lon> column per cell)
        |
frames.drop_future                  (pure: drop hours after now; the API also returns forecasts)
frames.merge_incremental            (pure, --incremental: replace rows from the overlap start)
        |
storage.save_parquet / save_rainfall   (I/O: local parquet; BigQuery WRITE_TRUNCATE with --write-bq)
```

In incremental mode the cells are recovered from the existing column names
(`frames.parse_cell_column`), so the grid isn't re-discovered. `analysis`
(`make rainfall-rank`) is offline: it reads the hourly water-level and
rainfall parquets, restricts to the train split (`preprocessing.split_data`)
and ranks cells per station by the peak lagged correlation between rain and
water-level rise (`level_rise`, `lagged_correlation`, `rank_cells` — pure and
unit-tested in `tests/rainfall/`).

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
features.encode_calendar                                     (pure: hour/month/day_of_week -> sin/cos)
        |
features.top_cells_by_station       (pure: rain cells per station from rainfall_cell_ranking.csv)
bigquery_io.load_rainfall_cells     (I/O: reads those cells from rainfall_hourly)
features.rain_features / fit_rain_scalers / apply_rain_scalers   (pure: catchment mean,
                                     1..24 h sums over the full history, log1p + MinMax fit on train)
        |
metadata.build_metadata             (pure: feature cols per station, rain cells, fill medians)
storage.save_preprocessed_data / save_metadata / save_scalers  (I/O: writes *_<granularity>)
```

Rain features are hourly-only and switched by `rainfall.enabled` in
`config/preprocessing.yaml`. Every model gets `base_feature_cols` (all
stations + calendar); `feature_cols_by_station` adds the target station's
rain columns. Rain scalers are stored in the scalers table next to the
station scalers, keyed by column name. `splitting`, `imputation`, `scaling`,
`features` and `metadata` have no BigQuery dependency and are unit-tested
directly (see `tests/preprocessing/`). `bigquery_io` and `storage` are I/O
boundaries and are not unit-tested — they're exercised by actually running
the pipeline against a real project/dataset.

## `src/prediction` (per-request forecast)

Entry point: `predict.main()` -> `pipeline.forecast_latest()`.

```
best_model.load_best_model     (I/O: reads model_selection + {model}_weights;
                                 n_features per station from metadata)
data.load_recent_scaled        (I/O: reads prediction.yaml's station_features + rainfall,
                                 rebuilds features with preprocessing's functions,
                                 stored fill medians and scalers)
        |
features.split_model_name / feature_cols_for   (pure: "_norain" variants, columns per station)
windowing.torch_window / prophet_frame   (pure: shape data for inference)
        |
inference.forecast_torch / forecast_prophet   (runs the loaded model)
        |
scalers.inverse_transform      (pure: scaled prediction -> cm)
        |
storage.save_forecast          (I/O: optional, --write-bq)
```

`features`, `windowing` and `scalers.inverse_transform` are pure and
unit-tested (`tests/prediction/`). `data.load_recent_scaled` imports the
feature functions from `preprocessing` instead of re-implementing them, and
takes the fill medians, rain cells and scalers from the stored metadata and
scalers tables, so serving features match training exactly. Metadata from
before the rain/calendar change (no `fill_medians`/`calendar_feature_cols`)
is still served the old way. It passes its own tables from
`config/prediction.yaml`, so switching `preprocessing`'s granularity never
changes what the deployed model receives.

## Config loading

`src/settings.py` reads `config/{name}.yaml` relative to the repo root at
import time. `raw_preprocessing/config.py`, `rainfall/config.py`,
`preprocessing/config.py` and `prediction/config.py` each call `load_config` once at module import and
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
