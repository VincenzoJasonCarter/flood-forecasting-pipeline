import pandas as pd

from raw_preprocessing.config import CALENDAR_COLS
from raw_preprocessing.features import add_calendar_features


def _frame(start, periods):
    index = pd.date_range(start, periods=periods, freq="h")
    return pd.DataFrame({"Pos A": range(periods)}, index=index)


def test_add_calendar_features_adds_every_calendar_col():
    df = add_calendar_features(_frame("2024-01-06", 2))  # Saturday

    assert list(df.columns) == ["Pos A"] + CALENDAR_COLS
    assert df["is_weekend"].tolist() == [1, 1]
    assert df["day_of_week"].tolist() == [5, 5]


def test_add_calendar_features_marks_indonesian_holidays():
    # 2024-08-17 is Indonesian Independence Day; 2024-08-19 is a regular Monday.
    df = add_calendar_features(pd.concat([_frame("2024-08-17", 24), _frame("2024-08-19", 24)]))

    assert df.loc["2024-08-17", "is_holiday"].eq(1).all()
    assert df.loc["2024-08-19", "is_holiday"].eq(0).all()


def test_is_rainy_season_keeps_training_encoding():
    df = add_calendar_features(pd.concat([_frame("2024-01-01", 1), _frame("2024-07-01", 1)]))

    # 0 = Nov–Apr (wet), 1 = May–Oct (dry) — inverted name, kept for trained models.
    assert df["is_rainy_season"].tolist() == [0, 1]


def test_add_calendar_features_on_daily_index_keeps_hour_column_at_zero():
    index = pd.date_range("2024-08-16", periods=3, freq="D")
    df = add_calendar_features(pd.DataFrame({"Pos A": [1.0, 2.0, 3.0]}, index=index))

    assert list(df.columns) == ["Pos A"] + CALENDAR_COLS
    assert df["hour"].tolist() == [0, 0, 0]
    assert df["is_holiday"].tolist() == [0, 1, 0]  # 2024-08-17
