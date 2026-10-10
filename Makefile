# High-level commands. Recipes stick to `cd` + `uv run` so they work whether
# make runs them through sh or cmd.exe (GnuWin32 make on Windows).
#
# Extra CLI flags go through ARGS, e.g.:
#   make raw-preprocess ARGS="--start 2024-01-01 --end 2024-12-31"
#   make raw-preprocess ARGS="--granularity daily"
#   make preprocess ARGS="--granularity daily"
#   make predict ARGS="--station \"Bendung Katulampa\" --horizon 1 3"

ARGS ?=

# Sel hujan per stasiun yang diambil histori penuhnya (make rainfall-bq).
TOP ?= 3

# Load SIBANJIR_TOKEN (and anything else) from .env when it exists.
ENV_FILE := $(if $(wildcard .env),--env-file ../.env,)

.PHONY: help venv sync test raw-preprocess raw-preprocess-bq raw-preprocess-incremental rainfall rainfall-survey rainfall-bq rainfall-incremental rainfall-rank preprocess predict

help:
	@echo Targets:
	@echo   venv               create .venv and install dependencies, skipped if .venv exists
	@echo   sync               install/update dependencies from uv.lock
	@echo   test               run unit tests
	@echo   raw-preprocess     API crawl to artifacts/station_features_GRANULARITY.parquet
	@echo   raw-preprocess-bq  same, and write tables.station_features_GRANULARITY to BigQuery
	@echo   raw-preprocess-incremental  re-crawl last days from max date in BigQuery, merge, rewrite table
	@echo   rainfall           Open-Meteo hourly rain per grid cell to artifacts/rainfall_hourly.parquet
	@echo   rainfall-survey    step 1: all cells, one wet season, to artifacts/rainfall_survey.parquet
	@echo   rainfall-rank      step 2: rank cells per station by lagged correlation, train period only
	@echo   rainfall-bq        step 3: full history of the TOP=3 best cells per station to tables.rainfall_hourly
	@echo   rainfall-incremental  re-fetch last days from max date in BigQuery, merge, rewrite table
	@echo   preprocess         station_features_GRANULARITY to preprocessed_data/metadata/scalers_GRANULARITY
	@echo   predict            run the forecast pipeline
	@echo GRANULARITY comes from config/raw_preprocessing.yaml or config/preprocessing.yaml,
	@echo override per run with ARGS="--granularity daily"
	@echo Pass extra flags with ARGS, e.g. make raw-preprocess ARGS="--end 2026-08-25"

venv: .venv

.venv:
	uv venv
	uv sync

sync:
	uv sync

test:
	uv run pytest

raw-preprocess:
	cd src && uv run $(ENV_FILE) python -m raw_preprocessing $(ARGS)

raw-preprocess-bq:
	cd src && uv run $(ENV_FILE) python -m raw_preprocessing --write-bq $(ARGS)

raw-preprocess-incremental:
	cd src && uv run $(ENV_FILE) python -m raw_preprocessing --incremental --write-bq $(ARGS)

rainfall:
	cd src && uv run python -m rainfall $(ARGS)

rainfall-survey:
	cd src && uv run python -m rainfall --survey $(ARGS)

rainfall-bq:
	cd src && uv run python -m rainfall --select-top $(TOP) --write-bq $(ARGS)

rainfall-incremental:
	cd src && uv run python -m rainfall --incremental --write-bq $(ARGS)

rainfall-rank:
	cd src && uv run python -m rainfall.analysis $(ARGS)

preprocess:
	cd src && uv run python -m preprocessing $(ARGS)

predict:
	uv run python main.py $(ARGS)
