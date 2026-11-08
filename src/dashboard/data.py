"""BigQuery reads for the dashboard: latest forecast, recent water levels, catchment rain and the model in use.

Tidak mengimpor package `prediction` (yang menarik torch/prophet): tabel dibaca
langsung dari config/prediction.yaml, jadi dashboard cukup butuh bigquery + dash.
"""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from bq import make_client, run_query, scalar_param, to_naive_datetime_index
from settings import load_config

logger = logging.getLogger(__name__)

_prediction = load_config("prediction")
_dashboard = load_config("dashboard")

GRANULARITY = _prediction["granularity"]
UNIT = {"hourly": "jam", "daily": "hari"}[GRANULARITY]
STEP_HOURS = {"hourly": 1, "daily": 24}[GRANULARITY]  # tabel hujan selalu per jam, apa pun granularity TMA
HISTORY_STEPS = int(_dashboard["history_steps"])
REFRESH_SECONDS = int(_dashboard["refresh_seconds"])
RISE_THRESHOLD_CM = float(_dashboard["rise_threshold_cm"])
REPORT = _dashboard["laporan"]  # {trend_steps, near_limit_cm, heavy_rain_mm, tindakan}
STATIONS = _dashboard["stations"]  # {nama kolom: {label, aliran, lat, lon, siaga}}, urutan = urutan di papan status

_PREFIX = f"{_prediction['project']}.{_prediction['dataset']}"
_tables = _prediction["tables"]
FORECAST_TABLE = f"{_PREFIX}.{_tables['forecast_output']}"
STATION_FEATURES_TABLE = f"{_PREFIX}.{_tables['station_features']}"
RAINFALL_TABLE = f"{_PREFIX}.{_tables['rainfall']}"
METADATA_TABLE = f"{_PREFIX}.{_tables['metadata']}"
MODEL_SELECTION_TABLE = f"{_PREFIX}.{_tables['model_selection']}"

_TIME_COLS = ("as_of", "forecast_time", "generated_at")
_CACHE_TTL_S = 30
_QUERY_TIMEOUT_S = 60  # halaman lebih baik cepat menyajikan snapshot lama daripada menunggu 10 menit

_lock = threading.Lock()  # satu pembacaan BigQuery pada satu waktu
_client = None
_cache = {"at": float("-inf"), "value": None, "error": None}
_history = {}  # (pos, langkah) -> (waktu baca, DataFrame); filter rentang grafik di halaman detail


def _get_client():
    global _client
    if _client is None:
        _client = make_client(_prediction["project"], _prediction["location"])
    return _client


def load_forecast(client):
    """Forecast run terbaru (as_of terakhir), baris terbaru per (stasiun, horizon); kolom waktu tanpa tz."""
    df = run_query(client, "dashboard/forecast_latest", table=FORECAST_TABLE, timeout=_QUERY_TIMEOUT_S)
    for col in _TIME_COLS:
        if df[col].dt.tz is not None:
            df[col] = df[col].dt.tz_convert(None)
    return df


def _recent(client, table, n):
    df = run_query(client, "dashboard/recent_rows", table=table, params=[scalar_param("n", "INT64", n)],
                   timeout=_QUERY_TIMEOUT_S)
    return to_naive_datetime_index(df).sort_index()


def load_levels(client):
    """TMA aktual HISTORY_STEPS langkah terakhir, index datetime urut naik."""
    return _recent(client, STATION_FEATURES_TABLE, HISTORY_STEPS)


def load_history(station, steps):
    """TMA satu pos, `steps` langkah terakhir (kolom = nama pos), untuk rentang grafik di atas history_steps.

    Terpisah dari snapshot supaya setahun data per jam tidak ikut dibaca tiap refresh; di-cache per
    (pos, langkah) selama refresh_seconds. Error dibiarkan naik ke pemanggil.
    """
    key = (station, steps)
    hit = _history.get(key)
    if hit and time.monotonic() - hit[0] < REFRESH_SECONDS:
        return hit[1]
    df = run_query(_get_client(), "dashboard/station_history", table=STATION_FEATURES_TABLE, columns=[station],
                   params=[scalar_param("n", "INT64", steps)], timeout=_QUERY_TIMEOUT_S)
    df = to_naive_datetime_index(df).sort_index()
    _history[key] = (time.monotonic(), df)
    return df


def load_rain(client):
    """Hujan per sel grid (mm/jam, kolom rain_<lat>_<lon>) untuk jendela waktu yang sama dengan TMA."""
    return _recent(client, RAINFALL_TABLE, HISTORY_STEPS * STEP_HOURS)


def load_model(client):
    """{best_model, selection_metric, stat, stat_value, rain_cells}: model yang dipakai forecast dan sel hujan per pos.

    stat = "median" atau "mean" (tabel model_selection lama menyimpan mean_value), stat_value angkanya.
    """
    selection = run_query(client, "prediction/model_selection_latest", table=MODEL_SELECTION_TABLE,
                          timeout=_QUERY_TIMEOUT_S)
    metadata = run_query(client, "prediction/metadata_latest", table=METADATA_TABLE, timeout=_QUERY_TIMEOUT_S)
    row = selection.iloc[0].to_dict() if not selection.empty else {}
    info = {"best_model": row.get("best_model"), "selection_metric": row.get("selection_metric")}
    for stat in ("median", "mean"):
        value = row.get(f"{stat}_value")
        if value is not None and pd.notna(value):
            info["stat"], info["stat_value"] = stat, float(value)
            break
    payload = json.loads(metadata.iloc[0]["payload"]) if not metadata.empty else {}
    info["rain_cells"] = payload.get("rain_cells_by_station") or {}
    return info


def _optional(loader, client, what):
    """Hujan dan info model hanya pelengkap: kalau gagal, dashboard tetap jalan tanpa bagian itu."""
    try:
        return loader(client)
    except Exception:
        logger.exception("Gagal membaca %s", what)
        return None


def _query_all(client):
    """Empat bacaan independen, paralel: waktu tunggu = query terlama, bukan jumlahnya."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        forecast = pool.submit(load_forecast, client)
        levels = pool.submit(load_levels, client)
        rain = pool.submit(_optional, load_rain, client, "hujan")
        model = pool.submit(_optional, load_model, client, "info model")
        return {"forecast": forecast.result(), "levels": levels.result(), "rain": rain.result(),
                "model": model.result()}


def _expired():
    return time.monotonic() - _cache["at"] > _CACHE_TTL_S


def _served():
    if _cache["value"] is None and _cache["error"] is not None:
        raise _cache["error"]
    return _cache["value"]


def load_snapshot(force=False):
    """Dict forecast, levels, rain, model; di-cache sebentar supaya callback Dash tidak menembak BigQuery tiap kali.

    forecast dan levels wajib, rain dan model None kalau gagal dibaca. `force` (tombol Muat ulang)
    membaca ulang walau cache masih segar. Kalau BigQuery gagal, snapshot terakhir yang berhasil tetap
    disajikan (umurnya terlihat di "Data terakhir"), dan kegagalan ikut di-cache selama TTL supaya tiap
    callback tidak mencoba ulang. Selama satu callback membaca, callback lain langsung memakai snapshot
    lama alih-alih antre di belakangnya; hanya pembacaan pertama yang ditunggu.
    """
    if not force and not _expired():
        return _served()
    if not _lock.acquire(blocking=_cache["value"] is None):
        return _cache["value"]
    try:
        if force or _expired():
            try:
                _cache["value"], _cache["error"] = _query_all(_get_client()), None
            except Exception as exc:
                _cache["error"] = exc
                if _cache["value"] is not None:
                    logger.exception("Gagal membaca BigQuery; snapshot sebelumnya tetap dipakai")
            _cache["at"] = time.monotonic()
        return _served()
    finally:
        _lock.release()
