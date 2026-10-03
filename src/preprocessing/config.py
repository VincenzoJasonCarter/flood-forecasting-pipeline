"""Constants shared across the preprocessing package.

Project/dataset/table paths datang dari config/preprocessing.yaml. Setiap
granularity (hourly/daily) punya set tabel input/output sendiri.
"""

from settings import load_config

_config = load_config("preprocessing")

PROJECT_ID = _config["project"]
DATASET = _config["dataset"]
LOCATION = _config["location"]

GRANULARITIES = ("hourly", "daily")
GRANULARITY = _config["granularity"]
if GRANULARITY not in GRANULARITIES:
    raise ValueError(f"granularity di config/preprocessing.yaml harus salah satu dari {GRANULARITIES}, "
                     f"bukan {GRANULARITY!r}")

CALENDAR_COLS = ["hour", "month", "day_of_week", "is_weekend", "is_holiday", "is_rainy_season"]

TRAIN_RATIO = 0.70
VAL_RATIO = 0.15

WRITE_DISPOSITION = "WRITE_TRUNCATE"  # atau "WRITE_APPEND"

_tables = _config["tables"]


def table_id(name, granularity=GRANULARITY):
    """Path BigQuery lengkap untuk tabel `name` (station_features,
    preprocessed_data, metadata, scalers) pada granularity tertentu."""
    return f"{PROJECT_ID}.{DATASET}.{_tables[granularity][name]}"
