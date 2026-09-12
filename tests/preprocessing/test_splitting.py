import pandas as pd

from preprocessing.splitting import get_station_cols, split_data


def test_get_station_cols_excludes_calendar_columns():
    df = pd.DataFrame(columns=["hour", "month", "station_a", "station_b"])

    assert get_station_cols(df) == ["station_a", "station_b"]


def test_split_data_respects_train_val_test_ratios_in_order():
    df = pd.DataFrame({"station_a": range(100)})

    df_train, df_val, df_test = split_data(df)

    assert len(df_train) == 70
    assert len(df_val) == 15
    assert len(df_test) == 15
    # Chronological, non-overlapping split.
    assert df_train.index[-1] < df_val.index[0] < df_test.index[0]
