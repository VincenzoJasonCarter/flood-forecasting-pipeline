import numpy as np
import pandas as pd

from raw_preprocessing.resampling import resample_hourly, to_daily_max, to_wide


def test_resample_hourly_averages_within_hour_and_marks_empty_hours_nan():
    df = pd.DataFrame({
        "station_name": ["Pos A"] * 3,
        "datetime": pd.to_datetime(["2024-01-01 00:00", "2024-01-01 00:30", "2024-01-01 02:00"]),
        "water_level": [10.0, 20.0, 40.0],
    })

    out = resample_hourly(df)

    assert out["water_level"].iloc[0] == 15.0
    assert out["water_level"].isna().iloc[1]  # 01:00 had no observations
    assert out["water_level"].iloc[2] == 40.0


def test_to_wide_builds_continuous_hourly_grid_across_stations():
    df_long = pd.DataFrame({
        "station_name": ["Pos A", "Pos B"],
        "datetime": pd.to_datetime(["2024-01-01 00:00", "2024-01-01 02:00"]),
        "water_level": [10.0, 30.0],
    })

    wide = to_wide(df_long)

    assert list(wide.columns) == ["Pos A", "Pos B"]
    assert len(wide) == 3  # 00:00, 01:00, 02:00
    assert wide.isna().sum().tolist() == [2, 2]


def test_to_daily_max_takes_daily_peak_and_keeps_all_nan_days_nan():
    index = pd.date_range("2024-01-01", periods=72, freq="h")
    values = np.full(72, 10.0)
    values[5] = 80.0          # day 1 peak
    values[24:48] = np.nan    # day 2 fully missing
    values[60] = 35.0         # day 3 peak
    wide = pd.DataFrame({"Pos A": values}, index=index)

    daily = to_daily_max(wide)

    assert len(daily) == 3
    assert daily.index[0] == pd.Timestamp("2024-01-01")
    assert daily["Pos A"].iloc[0] == 80.0
    assert np.isnan(daily["Pos A"].iloc[1])
    assert daily["Pos A"].iloc[2] == 35.0
