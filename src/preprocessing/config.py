"""Constants shared across the preprocessing package.

Project/dataset/table paths datang dari config/preprocessing.yaml.
"""

from settings import load_config

_config = load_config("preprocessing")

PROJECT_ID = _config["project"]
DATASET = _config["dataset"]
LOCATION = _config["location"]

CALENDAR_COLS = ["hour", "month", "day_of_week", "is_weekend", "is_holiday", "is_rainy_season"]

TRAIN_RATIO = 0.70
VAL_RATIO = 0.15

WRITE_DISPOSITION = "WRITE_TRUNCATE"  # atau "WRITE_APPEND"

_tables = _config["tables"]
STATION_FEATURES_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['station_features']}"
PREPROCESSED_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['preprocessed_data']}"
METADATA_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['metadata']}"
SCALERS_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['scalers']}"
