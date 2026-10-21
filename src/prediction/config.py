"""Constants shared across the prediction package.

Project/dataset/table paths, granularity, LOOKBACK dan HORIZONS datang dari
config/prediction.yaml. LOOKBACK/HORIZONS (dalam langkah waktu granularity
tsb.) harus selaras dengan hyperparameter yang dipakai saat training
(notebooks_training/02-04).
"""

import pandas as pd

from settings import load_config

_config = load_config("prediction")

PROJECT_ID = _config["project"]
DATASET = _config["dataset"]
LOCATION = _config["location"]

GRANULARITY = _config["granularity"]
if GRANULARITY not in _config["model"]:
    raise ValueError(f"granularity di config/prediction.yaml harus salah satu dari "
                     f"{tuple(_config['model'])}, bukan {GRANULARITY!r}")

_model = _config["model"][GRANULARITY]
HORIZONS = [int(h) for h in _model["horizons"]]
LOOKBACK = int(_model["lookback"])
TIME_STEP = pd.Timedelta(**_model["step"])

_tables = _config["tables"]
MODEL_SELECTION_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['model_selection']}"
STATION_FEATURES_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['station_features']}"
METADATA_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['metadata']}"
SCALERS_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['scalers']}"
FORECAST_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['forecast_output']}"
RAINFALL_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['rainfall']}"
_WEIGHTS_SUFFIX = _tables["weights_suffix"]


def weights_table(model_name):
    return f"{PROJECT_ID}.{DATASET}.{model_name}_{_WEIGHTS_SUFFIX}"
