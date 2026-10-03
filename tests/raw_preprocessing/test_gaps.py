import numpy as np
import pandas as pd

from raw_preprocessing.gaps import fill_gaps, gap_lengths


def test_gap_lengths_counts_each_consecutive_nan_run():
    s = pd.Series([np.nan, 1.0, np.nan, np.nan, 2.0, 3.0, np.nan])

    assert gap_lengths(s) == [1, 2, 1]


def test_gap_lengths_empty_when_no_nans():
    assert gap_lengths(pd.Series([1.0, 2.0])) == []


def test_fill_gaps_interpolates_short_gaps_in_time():
    index = pd.date_range("2024-01-01", periods=4, freq="h")
    df = pd.DataFrame({"Pos A": [10.0, np.nan, np.nan, 40.0]}, index=index)

    filled = fill_gaps(df, limit=6)

    assert filled["Pos A"].tolist() == [10.0, 20.0, 30.0, 40.0]


def test_fill_gaps_leaves_middle_of_long_gap_nan():
    index = pd.date_range("2024-01-01", periods=12, freq="h")
    values = [10.0] + [np.nan] * 10 + [20.0]
    df = pd.DataFrame({"Pos A": values}, index=index)

    filled = fill_gaps(df, limit=2)

    # interpolate + ffill fill 2 each from the left, bfill fills 2 from the right.
    assert filled["Pos A"].isna().sum() == 4
