import json

import numpy as np
import pandas as pd
import pytest

from preprocessing.config import CALENDAR_COLS
from preprocessing.features import (CALENDAR_FEATURE_COLS, apply_rain_scalers, encode_calendar,
                                    fit_rain_scalers, rain_feature_col, rain_features, top_cells_by_station)
from preprocessing.imputation import compute_hourly_medians, medians_from_json, medians_to_json
from preprocessing.metadata import build_metadata


def _calendar_frame():
    idx = pd.date_range("2024-01-01", periods=48, freq="h", name="datetime")
    df = pd.DataFrame({"Station A": 0.5}, index=idx)
    df["hour"] = idx.hour
    df["month"] = idx.month
    df["day_of_week"] = idx.dayofweek
    df["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    df["is_holiday"] = 0
    df["is_rainy_season"] = 0
    return df


def test_encode_calendar_replaces_raw_columns_with_sin_cos():
    out = encode_calendar(_calendar_frame())
    assert out.columns.tolist() == ["Station A"] + CALENDAR_FEATURE_COLS
    assert out[CALENDAR_FEATURE_COLS].abs().max().max() <= 1.0


def test_encode_calendar_makes_midnight_and_23h_neighbours():
    out = encode_calendar(_calendar_frame())
    h0, h23, h12 = (out.loc[f"2024-01-01 {h:02d}:00", ["hour_sin", "hour_cos"]].to_numpy() for h in (0, 23, 12))
    assert np.linalg.norm(h0 - h23) < np.linalg.norm(h0 - h12)


def test_calendar_cols_cover_every_raw_calendar_column():
    encoded = {c.rsplit("_", 1)[0] for c in CALENDAR_FEATURE_COLS if c.endswith(("_sin", "_cos"))}
    assert encoded | {c for c in CALENDAR_FEATURE_COLS if c in CALENDAR_COLS} == set(CALENDAR_COLS)


def test_top_cells_by_station_keeps_order_and_skips_nan():
    ranking = pd.DataFrame([
        {"station": "A", "cell": "c1", "corr": 0.2},
        {"station": "A", "cell": "c2", "corr": 0.5},
        {"station": "A", "cell": "c3", "corr": float("nan")},
        {"station": "B", "cell": "c3", "corr": 0.4},
    ])
    assert top_cells_by_station(ranking, 2) == {"A": ["c2", "c1"], "B": ["c3"]}


def _rain():
    idx = pd.date_range("2024-01-01", periods=6, freq="h", name="datetime")
    return pd.DataFrame({"c1": [0, 2, 0, 4, 0, 0], "c2": [0, 0, 2, 0, 0, 0]}, index=idx, dtype=float)


def test_rain_features_average_cells_then_accumulate():
    rain = _rain()
    feats, cols = rain_features(rain, {"Pos A": ["c1", "c2"]}, [1, 3], {"Pos A": "Pos_A"}, rain.index)

    assert cols == {"Pos A": [rain_feature_col("Pos_A", 1), rain_feature_col("Pos_A", 3)]}
    assert feats["rain_Pos_A_1h"].tolist() == [0, 1, 1, 2, 0, 0]
    assert feats["rain_Pos_A_3h"].tolist() == [0, 1, 2, 4, 3, 2]


def test_rain_features_fill_hours_without_rain_data_with_zero():
    rain = _rain()
    index = pd.date_range("2024-01-01 04:00", periods=4, freq="h", name="datetime")  # 2 jam di luar data
    feats, _ = rain_features(rain, {"Pos A": ["c1"]}, [1], {"Pos A": "Pos_A"}, index)
    assert feats["rain_Pos_A_1h"].tolist() == [0, 0, 0, 0]


def test_rain_features_reject_missing_cells():
    with pytest.raises(KeyError):
        rain_features(_rain(), {"Pos A": ["c9"]}, [1], {"Pos A": "Pos_A"}, _rain().index)


def test_rain_scalers_fit_log1p_range_of_train():
    feats = pd.DataFrame({"r": [0.0, 1.0, 9.0, 99.0]})
    scalers = fit_rain_scalers(feats.iloc[:3], ["r"])
    out = apply_rain_scalers(feats, scalers, ["r"])

    assert out["r"].iloc[0] == 0.0
    assert out["r"].iloc[2] == pytest.approx(1.0)
    assert out["r"].iloc[3] == pytest.approx(np.log1p(99) / np.log1p(9))  # di luar range train > 1


def test_medians_json_roundtrip():
    idx = pd.DatetimeIndex(["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-02 00:00"])
    medians = compute_hourly_medians(pd.DataFrame({"A": [10.0, 30.0, 20.0]}, index=idx), ["A"])
    back = medians_from_json(json.loads(json.dumps(medians_to_json(medians))))
    pd.testing.assert_series_equal(back["A"], medians["A"], check_names=False, check_index_type=False)


def test_build_metadata_feature_sets():
    medians = {"A": pd.Series({0: 1.0}), "B": pd.Series({0: 2.0})}
    meta = build_metadata(["A", "B"], {"A": "A", "B": "B"}, medians, "hourly",
                          {"A": ["c1"]}, {"A": ["rain_A_1h", "rain_A_3h"]}, [1, 3])

    base = ["A", "B"] + CALENDAR_FEATURE_COLS
    assert meta["base_feature_cols"] == base
    assert meta["feature_cols"] == base
    assert meta["feature_cols_by_station"] == {"A": base + ["rain_A_1h", "rain_A_3h"], "B": base}
    assert meta["rain_accum_hours"] == [1, 3]
    json.dumps(meta)  # harus bisa disimpan sebagai payload JSON
