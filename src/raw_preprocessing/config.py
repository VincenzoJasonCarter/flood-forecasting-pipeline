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

# Pembersihan glitch sensor sebelum pengisian gap (outliers.clean_glitches).
# Notebook asli TIDAK membersihkan apa pun (outlier hanya ditandai), padahal
# glitch seperti -1801 di Waduk Pluit atau 1000 di Pos Depok menarik range
# MinMaxScaler sehingga sinyal normal tergencet ke rentang yang sangat sempit.
# Set False untuk mereproduksi station_features versi notebook.
CLEAN_GLITCHES = True

# Range nilai yang masuk akal (cm, inklusif); di luar range -> NaN. Sungai
# tidak bisa di bawah 0. Muka air Waduk Pluit normalnya sekitar -180; nilai
# +160..+200 di data adalah tanda yang terbalik (banjir 2025-01-29 hanya
# memuncak di +30).
DEFAULT_VALID_RANGE = (0.0, float("inf"))
VALID_RANGE = {"Waduk Pluit": (-300.0, 100.0)}

# Spike: run 1..SPIKE_MAX_LEN jam yang menyimpang > SPIKE_MIN_DEV cm dari
# KEDUA tetangganya ke arah yang sama, dengan tetangga yang datar dan saling
# dekat — glitch lalu balik ke level semula (detail: outliers.spike_mask).
# Banjir asli (tetangganya sedang naik/surut) tidak memenuhi syarat ini.
# SPIKE_MAX_LEN = 3 sudah membuang puncak banjir Katulampa 2022-10-09
# (60 -> 220 -> 200 -> 140 -> 80); glitch di data mentah hampir selalu 1 jam.
SPIKE_MIN_DEV = 50        # cm
SPIKE_MAX_LEN = 2         # jam
SPIKE_MAX_NEIGHBOR_GAP = GAP_LIMIT  # jam; tetangga lebih jauh dari ini tidak dipakai

WRITE_DISPOSITION = "WRITE_TRUNCATE"

_tables = _config["tables"]


def station_features_table(granularity=GRANULARITY):
    return f"{PROJECT_ID}.{DATASET}.{_tables['station_features'][granularity]}"


def default_output_path(granularity=GRANULARITY):
    return CONFIG_DIR.parent / "artifacts" / f"{_tables['station_features'][granularity]}.parquet"
