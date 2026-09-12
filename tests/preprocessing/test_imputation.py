import pandas as pd

from preprocessing.imputation import compute_hourly_medians, fill_nan_hourly_median


def _hourly_df(values):
    index = pd.date_range("2024-01-01", periods=len(values), freq="h")
    return pd.DataFrame({"station_a": values}, index=index)


def test_compute_hourly_medians_groups_by_hour_of_day():
    # Two days at hourly resolution: hour 0 -> [10, 20], hour 1 -> [30, 40].
    index = pd.DatetimeIndex(
        ["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-02 00:00", "2024-01-02 01:00"]
    )
    df = pd.DataFrame({"station_a": [10.0, 30.0, 20.0, 40.0]}, index=index)
    medians = compute_hourly_medians(df, ["station_a"])

    assert medians["station_a"][0] == 15.0
    assert medians["station_a"][1] == 35.0


def test_fill_nan_hourly_median_fills_only_missing_values():
    df = _hourly_df([10.0, None, 20.0, 40.0])
    hourly_medians = {"station_a": pd.Series({0: 15.0, 1: 35.0})}

    filled = fill_nan_hourly_median(df, hourly_medians, ["station_a"])

    assert filled["station_a"].isna().sum() == 0
    assert filled["station_a"].iloc[1] == 35.0  # hour 1 -> median for hour 1
    assert filled["station_a"].iloc[0] == 10.0  # untouched original value


def test_fill_nan_hourly_median_is_noop_without_nans():
    df = _hourly_df([10.0, 20.0, 30.0, 40.0])
    hourly_medians = {"station_a": pd.Series({0: 15.0, 1: 35.0})}

    filled = fill_nan_hourly_median(df, hourly_medians, ["station_a"])

    pd.testing.assert_series_equal(filled["station_a"], df["station_a"])
