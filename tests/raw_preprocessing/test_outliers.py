import pandas as pd

from raw_preprocessing.outliers import clean_isolated_spikes, flag_outliers


def _long(values):
    return pd.DataFrame({
        "station_name": ["Pos A"] * len(values),
        "datetime": pd.date_range("2024-01-01", periods=len(values), freq="h"),
        "water_level": values,
    })


def test_flag_outliers_physical_flags_jumps_and_low_levels():
    df = flag_outliers(_long([10.0, 10.0, 100.0, 10.0, -60.0]))

    # 100 is a +90 jump, the next 10 is a -90 jump back, -60 is below the floor.
    assert df["outlier_physical"].tolist() == [False, False, True, True, True]
    assert df["outlier_any"].tolist()[2:] == [True, True, True]


def test_clean_isolated_spikes_only_removes_single_hour_spikes():
    isolated = pd.DataFrame({
        "station_name": ["Pos A"] * 5,
        "water_level": [10.0, 20.0, 99.0, 99.0, 30.0],
        "outlier_physical": [False, False, True, False, False],
    })
    consecutive = isolated.assign(outlier_physical=[False, True, True, False, False])

    cleaned = clean_isolated_spikes(isolated)
    untouched = clean_isolated_spikes(consecutive)

    assert cleaned["water_level"].tolist() == [10.0, 20.0, 59.5, 99.0, 30.0]
    assert untouched["water_level"].tolist() == consecutive["water_level"].tolist()
