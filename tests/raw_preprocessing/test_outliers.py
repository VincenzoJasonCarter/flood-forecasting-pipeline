import numpy as np
import pandas as pd

from raw_preprocessing.outliers import clean_glitches, flag_outliers, spike_mask


def _long(values):
    return pd.DataFrame({
        "station_name": ["Pos A"] * len(values),
        "datetime": pd.date_range("2024-01-01", periods=len(values), freq="h"),
        "water_level": values,
    })


def _hourly(values):
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="h"), dtype=float)


def test_flag_outliers_physical_flags_jumps_and_low_levels():
    df = flag_outliers(_long([10.0, 10.0, 100.0, 10.0, -60.0]))

    # 100 is a +90 jump, the next 10 is a -90 jump back, -60 is below the floor.
    assert df["outlier_physical"].tolist() == [False, False, True, True, True]
    assert df["outlier_any"].tolist()[2:] == [True, True, True]


def test_spike_mask_flags_runs_that_return_to_the_same_level():
    # Spike 1 jam, dip 1 jam, dan run 2 jam — semuanya kembali ke level semula.
    s = _hourly([40, 40, 300, 40, 40, 105, -190, 105, 105, 40, 440, 640, 40, 40])

    assert spike_mask(s).tolist() == [False, False, True, False, False, False, True, False,
                                      False, False, True, True, False, False]


def test_spike_mask_keeps_real_flood_peaks():
    # Diambil dari data asli: puncak yang tetangganya sedang naik/surut.
    floods = [
        [90, 90, 90, 202, 190, 160, 145, 130, 110],           # naik tiba-tiba, surut perlahan
        [20, 20, 20, 130, 80, 70, 50, 40],
        [10, 10, 98, 170, 90, 60, 40],                        # Katulampa 2021-06-22
        [100, 200, 210, 310, 350, 300, 230, 190, 170],        # Depok 2022-10-09
        [40, 60, 60, 220, 200, 140, 80, 60],                  # Katulampa 2022-10-09
        [-170, -110, -50, 0, 20, 30, 20, -5, -40, -75, -105],  # Waduk Pluit 2025-01-29
    ]

    for values in floods:
        assert not spike_mask(_hourly(values)).any(), values


def test_spike_mask_skips_nan_but_not_long_gaps():
    s = _hourly([-190, -190, np.nan, np.nan, 185, -175, -175])
    far = _hourly([-190, -190] + [np.nan] * 10 + [185, -175, -175])

    assert spike_mask(s).tolist() == [False, False, False, False, True, False, False]
    assert not spike_mask(far).any()


def test_clean_glitches_drops_out_of_range_then_spikes():
    df = pd.DataFrame({
        "Pos A": [80, 80, -185, 80, 80, 880, 80, 80],
        "Waduk Pluit": [-180, -180, 185, -180, -1801, -180, -185, -185],
    }, index=pd.date_range("2024-01-01", periods=8, freq="h"), dtype=float)

    cleaned, stats = clean_glitches(df, valid_range={"Waduk Pluit": (-300.0, 100.0)})

    assert cleaned["Pos A"].isna().tolist() == [False, False, True, False, False, True, False, False]
    assert cleaned["Waduk Pluit"].isna().tolist() == [False, False, True, False, True, False, False, False]
    assert stats.loc["Pos A"].to_dict() == {"out_of_range": 1, "spike": 1}
    assert stats.loc["Waduk Pluit"].to_dict() == {"out_of_range": 2, "spike": 0}
