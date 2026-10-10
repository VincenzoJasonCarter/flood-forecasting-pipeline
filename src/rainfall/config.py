"""Constants shared across the rainfall package.

API, grid, dan project/dataset/table paths datang dari config/rainfall.yaml.
"""

from settings import CONFIG_DIR, load_config

_config = load_config("rainfall")

PROJECT_ID = _config["project"]
DATASET = _config["dataset"]
LOCATION = _config["location"]

_api = _config["api"]
API_URL = _api["url"]
MODEL = _api["model"]
VARIABLE = _api["variable"]
TIMEZONE = _api["timezone"]
START_DATE = str(_api["start_date"])

_grid = _config["grid"]
BBOX = (_grid["lat_min"], _grid["lat_max"], _grid["lon_min"], _grid["lon_max"])
PROBE_STEP = _grid["probe_step"]

_fetch = _config["fetch"]
CELLS_PER_REQUEST = _fetch["cells_per_request"]
DAYS_PER_REQUEST = _fetch["days_per_request"]
OVERLAP_DAYS = _fetch["overlap_days"]
MINUTE_BUDGET = _fetch["minute_budget"]
HOUR_BUDGET = _fetch["hour_budget"]

COLUMN_PREFIX = "rain_"

_artifacts = CONFIG_DIR.parent / "artifacts"
_table = _config["tables"]["rainfall"]
RAINFALL_TABLE = f"{PROJECT_ID}.{DATASET}.{_table}"
DEFAULT_OUTPUT_PATH = _artifacts / f"{_table}.parquet"

_survey = _config["survey"]
SURVEY_START = str(_survey["start"])
SURVEY_END = str(_survey["end"])
SURVEY_OUTPUT_PATH = _artifacts / f"{_survey['output']}.parquet"
RANKING_PATH = _artifacts / "rainfall_cell_ranking.csv"
