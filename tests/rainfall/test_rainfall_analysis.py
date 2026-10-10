import numpy as np
import pandas as pd

from rainfall.analysis import lagged_correlation, level_rise, rank_cells
from rainfall.frames import cell_column


def _synthetic(lag=5, hours=2000, seed=0):
    """Hujan acak di dua sel; muka air naik `lag` jam setelah hujan di sel A saja."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=hours, freq="h", name="datetime")
    rain_a = rng.gamma(0.3, 5, hours) * (rng.random(hours) < 0.1)
    rain_b = rng.gamma(0.3, 5, hours) * (rng.random(hours) < 0.1)
    rise = pd.Series(rain_a, index=idx).shift(lag).fillna(0) + rng.normal(0, 0.1, hours).clip(0)
    level = 100 + rise.cumsum() - np.arange(hours) * rise.mean()  # resesi pelan supaya tidak naik terus
    a, b = cell_column(-6.7, 106.9), cell_column(-6.2, 106.6)
    rain = pd.DataFrame({a: rain_a, b: rain_b}, index=idx)
    return rain, level, a, b


def test_level_rise_ignores_falling_level():
    rise = level_rise(pd.Series([10.0, 12.0, 11.0, 15.0]))
    assert rise.tolist()[1:] == [2.0, 0.0, 4.0]


def test_lagged_correlation_peaks_at_true_lag():
    rain, level, a, _ = _synthetic(lag=5)
    corr = lagged_correlation(rain[a], level_rise(level), max_lag=12, smooth_hours=1)
    assert corr.idxmax() == 5


def test_rank_cells_puts_responsible_cell_first():
    rain, level, a, b = _synthetic(lag=5)
    ranking = rank_cells(rain, level, max_lag=12, smooth_hours=1)

    assert ranking["cell"].tolist() == [a, b]
    assert ranking.loc[0, "best_lag_h"] == 5
    assert (ranking.loc[0, "lat"], ranking.loc[0, "lon"]) == (-6.7, 106.9)


def test_rank_cells_uses_only_overlapping_hours():
    rain, level, a, _ = _synthetic(lag=3)
    ranking = rank_cells(rain, level.iloc[:500], max_lag=6, smooth_hours=1)
    assert ranking.loc[0, "cell"] == a
