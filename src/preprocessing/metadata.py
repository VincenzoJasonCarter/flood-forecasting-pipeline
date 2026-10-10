"""The preprocessing_metadata payload shared by training notebooks and serving."""

from .config import CALENDAR_COLS
from .features import CALENDAR_FEATURE_COLS
from .imputation import medians_to_json


def build_metadata(station_cols, column_map, hourly_medians, granularity,
                   rain_cells_by_station=None, rain_cols_by_station=None, rain_accum_hours=()):
    """Payload metadata.

    - base_feature_cols: semua stasiun + kalender (sin/cos), input semua model.
    - feature_cols_by_station: base + fitur hujan DAS stasiun target.
    - feature_cols: = base_feature_cols (kompatibel dengan pembaca lama).
    - fill_medians: median pengisi NaN dari periode train.
    """
    rain_cells_by_station = rain_cells_by_station or {}
    rain_cols_by_station = rain_cols_by_station or {}
    base = list(station_cols) + CALENDAR_FEATURE_COLS
    return {
        "granularity": granularity,
        "CALENDAR_COLS": CALENDAR_COLS,
        "calendar_feature_cols": CALENDAR_FEATURE_COLS,
        "station_cols": list(station_cols),
        "base_feature_cols": base,
        "feature_cols": base,
        "rain_accum_hours": list(rain_accum_hours),
        "rain_cells_by_station": rain_cells_by_station,
        "rain_cols_by_station": rain_cols_by_station,
        "feature_cols_by_station": {s: base + rain_cols_by_station.get(s, []) for s in station_cols},
        "column_map": column_map,  # station -> kolom BigQuery
        "fill_medians": medians_to_json(hourly_medians),
    }
