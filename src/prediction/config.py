"""Constants shared across the prediction package.

Project/dataset/table paths dan granularity datang dari config/prediction.yaml.
HORIZONS dan LOOKBACK (dalam langkah waktu granularity tsb.) harus selaras
dengan hyperparameter yang dipakai saat training (notebooks_training/02-04).
"""

import pandas as pd

from settings import load_config

_config = load_config("prediction")

PROJECT_ID = _config["project"]
DATASET = _config["dataset"]
LOCATION = _config["location"]

# Per granularity: panjang jendela input (lookback), horizon yang dilatih, dan
# durasi satu langkah waktu (untuk menghitung forecast_time = as_of + h * step).
_GRANULARITY_SETTINGS = {
    "hourly": {"lookback": 72, "horizons": [1, 3, 12], "time_step": pd.Timedelta(hours=1)},
    "daily": {"lookback": 3, "horizons": [1, 3, 7], "time_step": pd.Timedelta(days=1)},
}
GRANULARITY = _config["granularity"]
if GRANULARITY not in _GRANULARITY_SETTINGS:
    raise ValueError(f"granularity di config/prediction.yaml harus salah satu dari "
                     f"{tuple(_GRANULARITY_SETTINGS)}, bukan {GRANULARITY!r}")

HORIZONS = _GRANULARITY_SETTINGS[GRANULARITY]["horizons"]
LOOKBACK = _GRANULARITY_SETTINGS[GRANULARITY]["lookback"]
TIME_STEP = _GRANULARITY_SETTINGS[GRANULARITY]["time_step"]

_tables = _config["tables"]
MODEL_SELECTION_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['model_selection']}"
STATION_FEATURES_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['station_features']}"
METADATA_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['metadata']}"
SCALERS_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['scalers']}"
FORECAST_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['forecast_output']}"
_WEIGHTS_SUFFIX = _tables["weights_suffix"]


def weights_table(model_name):
    return f"{PROJECT_ID}.{DATASET}.{model_name}_{_WEIGHTS_SUFFIX}"
