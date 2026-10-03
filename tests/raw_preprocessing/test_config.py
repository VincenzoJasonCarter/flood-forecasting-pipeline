from preprocessing.config import CALENDAR_COLS as MODELLING_CALENDAR_COLS
from raw_preprocessing.config import CALENDAR_COLS, default_output_path, station_features_table


def test_calendar_cols_match_what_preprocessing_expects():
    # preprocessing.get_station_cols treats every non-calendar column as a
    # station, so the producer and consumer lists must stay identical.
    assert CALENDAR_COLS == MODELLING_CALENDAR_COLS


def test_output_table_and_parquet_follow_granularity():
    assert station_features_table("hourly").endswith(".station_features_hourly")
    assert station_features_table("daily").endswith(".station_features_daily")
    assert default_output_path("hourly").name == "station_features_hourly.parquet"
    assert default_output_path("daily").name == "station_features_daily.parquet"
