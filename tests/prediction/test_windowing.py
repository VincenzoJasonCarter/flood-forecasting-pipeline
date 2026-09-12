import pandas as pd
import pytest
import torch

from prediction.windowing import prophet_frame, torch_window


def test_torch_window_shape_matches_lookback_and_features():
    df = pd.DataFrame({"station_a": range(10), "station_b": range(10, 20)})

    window = torch_window(df, lookback=4)

    assert window.shape == (1, 4, 2)
    assert torch.equal(window[0, -1], torch.tensor([9.0, 19.0]))


def test_torch_window_raises_when_not_enough_rows():
    df = pd.DataFrame({"station_a": range(3)})

    with pytest.raises(RuntimeError):
        torch_window(df, lookback=5)


def test_prophet_frame_selects_last_row_with_ds_and_regressors():
    index = pd.date_range("2024-01-01", periods=3, freq="h", name="datetime")
    df = pd.DataFrame(
        {"target": [0.1, 0.2, 0.3], "other": [0.4, 0.5, 0.6]}, index=index
    )

    out = prophet_frame(df, target_station="target", other_stations=["other"])

    assert len(out) == 1
    assert list(out.columns) == ["ds", "y", "other"]
    assert out["ds"].iloc[0] == index[-1]
    assert out["y"].iloc[0] == pytest.approx(0.3)
