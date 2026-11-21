import io

import pandas as pd
import pytest
import torch

from prediction import best_model
from prediction.architectures import TORCH_ARCHITECTURES, HorizonOutput
from prediction.config import HORIZONS

META = {
    "feature_cols": ["A", "B", "cal"],
    "base_feature_cols": ["A", "B", "cal"],
    "feature_cols_by_station": {"A": ["A", "B", "cal", "rain_A_1h"], "B": ["A", "B", "cal"]},
}


def _blob(model):
    buf = io.BytesIO()
    torch.save(model.state_dict(), buf)
    return buf.getvalue()


@pytest.mark.parametrize("architecture", sorted(TORCH_ARCHITECTURES))
def test_architectures_output_shape_direct_and_mimo(architecture):
    x = torch.randn(5, 12, 4)
    build = TORCH_ARCHITECTURES[architecture]
    assert build(4).eval()(x).shape == (5,)
    assert build(4, n_outputs=3).eval()(x).shape == (5, 3)


def test_horizon_output_selects_one_column():
    torch.manual_seed(0)
    model = TORCH_ARCHITECTURES["tft"](4, n_outputs=3).eval()
    x = torch.randn(2, 12, 4)
    with torch.no_grad():
        full = model(x)
        for j in range(3):
            assert torch.equal(HorizonOutput(model, j)(x), full[:, j])


@pytest.fixture
def fake_bq(monkeypatch):
    """Ganti I/O BigQuery: rows = isi tabel bobot yang dikembalikan query."""
    state = {}
    monkeypatch.setattr(best_model, "load_metadata", lambda client: META)
    monkeypatch.setattr(best_model, "run_query", lambda client, name, table, params: state["rows"])
    return state


def test_load_mimo_weights_expands_to_every_horizon(fake_bq):
    torch.manual_seed(0)
    mimo = TORCH_ARCHITECTURES["tft"](4, n_outputs=len(HORIZONS)).eval()   # stasiun A: 4 fitur
    fake_bq["rows"] = pd.DataFrame({"station": ["A"], "horizon": pd.array([None], dtype="Int64"),
                                    "weights": [_blob(mimo)]})

    models = best_model.load_torch_models(client=None, model_name="tft")

    assert sorted(models["A"]) == sorted(HORIZONS)
    x = torch.randn(1, 12, 4)
    with torch.no_grad():
        expected = mimo(x)
        for j, h in enumerate(HORIZONS):
            assert torch.allclose(models["A"][h](x), expected[:, j])


def test_load_mimo_weights_with_horizon_filter(fake_bq):
    mimo = TORCH_ARCHITECTURES["tft"](4, n_outputs=len(HORIZONS))
    fake_bq["rows"] = pd.DataFrame({"station": ["A"], "horizon": pd.array([None], dtype="Int64"),
                                    "weights": [_blob(mimo)]})

    models = best_model.load_torch_models(client=None, model_name="tft", horizon=HORIZONS[1])

    assert list(models["A"]) == [HORIZONS[1]]


def test_load_mimo_weights_rejects_mismatched_horizons(fake_bq):
    wrong = TORCH_ARCHITECTURES["tft"](4, n_outputs=len(HORIZONS) + 1)
    fake_bq["rows"] = pd.DataFrame({"station": ["A"], "horizon": pd.array([None], dtype="Int64"),
                                    "weights": [_blob(wrong)]})

    with pytest.raises(RuntimeError, match="HORIZONS"):
        best_model.load_torch_models(client=None, model_name="tft")


def test_load_direct_weights_still_supported(fake_bq):
    direct = TORCH_ARCHITECTURES["gru"](3)   # stasiun B tanpa hujan: 3 fitur
    fake_bq["rows"] = pd.DataFrame({"station": ["B", "B"], "horizon": pd.array([1, 3], dtype="Int64"),
                                    "weights": [_blob(direct), _blob(direct)]})

    models = best_model.load_torch_models(client=None, model_name="gru")

    assert sorted(models["B"]) == [1, 3]
    assert models["B"][1](torch.randn(2, 12, 3)).shape == (2,)
