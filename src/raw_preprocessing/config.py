"""Constants shared across the raw_preprocessing package.

API endpoint dan project/dataset/table paths datang dari
config/raw_preprocessing.yaml.
"""

from settings import CONFIG_DIR, load_config

_config = load_config("raw_preprocessing")

PROJECT_ID = _config["project"]
DATASET = _config["dataset"]
LOCATION = _config["location"]

GRANULARITIES = ("hourly", "daily")
GRANULARITY = _config["granularity"]
if GRANULARITY not in GRANULARITIES:
    raise ValueError(f"granularity di config/raw_preprocessing.yaml harus salah satu dari {GRANULARITIES}, "
                     f"bukan {GRANULARITY!r}")

_api = _config["api"]
API_BASE_URL = _api["base_url"]
API_TOKEN_ENV = _api["token_env"]
START_DATE = str(_api["start_date"])

# Harus identik dengan preprocessing.config.CALENDAR_COLS — preprocessing
# memakai daftar ini untuk memisahkan kolom stasiun dari kolom kalender.
# Di output daily `hour` selalu 0, tapi tetap ada supaya skema kolomnya sama.
CALENDAR_COLS = ["hour", "month", "day_of_week", "is_weekend", "is_holiday", "is_rainy_season"]

# Mode incremental meng-crawl ulang N hari terakhir yang sudah ada di output
# dan mengganti baris-barisnya: jam-jam terakhir biasanya belum lengkap
# (laporan telat, hasil ffill). Hari pertama window hanya dipakai sebagai
# konteks interpolasi (barisnya tetap dari output lama), jadi harus > GAP_LIMIT.
INCREMENTAL_OVERLAP_DAYS = 3

RESAMPLE_FREQ = "h"  # grid pembersihan (outlier, pengisian gap)
DAILY_FREQ = "D"     # grid output granularity daily: max harian dari grid per jam
GAP_LIMIT = 6  # jam; batas NaN berturut-turut per langkah pengisian gap

# Ambang deteksi outlier (per stasiun).
IQR_K = 1.5
Z_THRESHOLD = 3
PHYSICAL_MIN_LEVEL = -50  # cm
PHYSICAL_MAX_JUMP = 50    # cm per jam
SPIKE_INTERP_LIMIT = 3

# Notebook asli menandai outlier tapi mem-pivot water_level mentah (bukan yang
# sudah dibersihkan), jadi station_features yang dipakai training TIDAK
# membuang spike. Default False mengikuti notebook — tapi perhatikan bahwa
# untuk granularity daily, max harian sensitif terhadap spike: satu spike
# 1 jam jadi nilai hari itu.
CLEAN_ISOLATED_SPIKES = False

WRITE_DISPOSITION = "WRITE_TRUNCATE"

_tables = _config["tables"]


def station_features_table(granularity=GRANULARITY):
    return f"{PROJECT_ID}.{DATASET}.{_tables['station_features'][granularity]}"


def default_output_path(granularity=GRANULARITY):
    return CONFIG_DIR.parent / "artifacts" / f"{_tables['station_features'][granularity]}.parquet"
