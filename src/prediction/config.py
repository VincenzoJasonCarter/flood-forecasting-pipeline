"""Constants shared across the prediction package.

Project/dataset/table paths datang dari config/prediction.yaml. HORIZONS dan
LOOKBACK harus selaras dengan hyperparameter yang dipakai saat training.
"""

from settings import load_config

_config = load_config("prediction")

PROJECT_ID = _config["project"]
DATASET = _config["dataset"]
LOCATION = _config["location"]

HORIZONS = [1, 3, 12]
LOOKBACK = 72

_tables = _config["tables"]
MODEL_SELECTION_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['model_selection']}"
METADATA_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['metadata']}"
SCALERS_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['scalers']}"
FORECAST_TABLE = f"{PROJECT_ID}.{DATASET}.{_tables['forecast_output']}"
_WEIGHTS_SUFFIX = _tables["weights_suffix"]


def weights_table(model_name):
    return f"{PROJECT_ID}.{DATASET}.{model_name}_{_WEIGHTS_SUFFIX}"
