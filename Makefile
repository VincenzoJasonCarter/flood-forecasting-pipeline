# High-level commands. Recipes stick to `cd` + `uv run` so they work whether
# make runs them through sh or cmd.exe (GnuWin32 make on Windows).
#
# Extra CLI flags go through ARGS, e.g.:
#   make raw-preprocess ARGS="--start 2024-01-01 --end 2024-12-31"
#   make raw-preprocess ARGS="--granularity hourly"
#   make preprocess ARGS="--granularity hourly"
#   make predict ARGS="--station \"Bendung Katulampa\" --horizon 1 3"

ARGS ?=

# Load SIBANJIR_TOKEN (and anything else) from .env when it exists.
ENV_FILE := $(if $(wildcard .env),--env-file ../.env,)

.PHONY: help venv sync test raw-preprocess raw-preprocess-bq raw-preprocess-incremental preprocess predict

help:
	@echo Targets:
	@echo   venv               create .venv and install dependencies, skipped if .venv exists
	@echo   sync               install/update dependencies from uv.lock
	@echo   test               run unit tests
	@echo   raw-preprocess     API crawl to artifacts/station_features_GRANULARITY.parquet
	@echo   raw-preprocess-bq  same, and write tables.station_features_GRANULARITY to BigQuery
	@echo   raw-preprocess-incremental  crawl from max date in BigQuery, APPEND new rows
	@echo   preprocess         station_features_GRANULARITY to preprocessed_data/metadata/scalers_GRANULARITY
	@echo   predict            run the forecast pipeline
	@echo GRANULARITY comes from config/raw_preprocessing.yaml or config/preprocessing.yaml,
	@echo override per run with ARGS="--granularity hourly"
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

preprocess:
	cd src && uv run python -m preprocessing $(ARGS)

predict:
	uv run python main.py $(ARGS)
