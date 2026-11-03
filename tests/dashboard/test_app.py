import pandas as pd
import pytest

from dashboard import data
from dashboard.figures import station_rows

# Dash memanggil serve_layout saat app.layout di-set; jangan sampai itu membaca BigQuery sungguhan
with pytest.MonkeyPatch.context() as mp:
    mp.setattr(data, "load_snapshot", lambda force=False: None)
    from dashboard import app

AS_OF = pd.Timestamp("2026-01-01 12:00")
COORDS = {"A": {"label": "Alfa", "aliran": "Tengah", "siaga": {3: 200, 2: 270, 1: 350}},
          "B": {"label": "Beta", "aliran": "Barat", "siaga": {3: 150, 2: 250, 1: 300}}}


def _snap(levels, preds):
    idx = pd.date_range(AS_OF - pd.Timedelta(hours=len(levels["A"]) - 1), AS_OF, freq="h")
    forecast = pd.DataFrame([
        {"model": "gru", "station": s, "horizon": h, "as_of": AS_OF, "forecast_time": AS_OF + pd.Timedelta(hours=h),
         "predicted_value_cm": v, "generated_at": AS_OF}
        for s, by_h in preds.items() for h, v in by_h.items()])
    return {"forecast": forecast, "levels": pd.DataFrame(levels, index=idx), "rain": None, "model": None}


def _rows(snap):
    return station_rows(snap["levels"], snap["forecast"], COORDS)


def test_finding_reports_a_station_in_siaga_now_even_if_the_forecast_recedes():
    snap = _snap({"A": [280.0, 280.0], "B": [100.0, 100.0]},
                 {"A": {1: 190.0, 3: 180.0}, "B": {1: 100.0, 3: 100.0}})
    text = app._finding(_rows(snap), [1, 3])
    assert text.startswith("A Siaga 2 (Siaga) sekarang: 280.0 cm, diprakirakan turun ke Normal pada +3 jam.")
    assert "Semua" not in text


def test_finding_handles_a_forecast_for_a_station_without_a_current_reading():
    snap = _snap({"A": [None, None], "B": [100.0, 100.0]}, {"A": {1: 280.0}, "B": {1: 100.0}})
    text = app._finding(_rows(snap), [1])
    assert text.startswith("A diprakirakan Siaga 2 (Siaga) pada +1 jam: 280.0 cm, TMA sekarang tidak terbaca.")


def test_finding_all_normal_only_when_now_and_forecast_are_normal():
    snap = _snap({"A": [100.0, 100.0], "B": [100.0, 100.0]}, {"A": {1: 100.0}, "B": {1: 100.0}})
    assert app._finding(_rows(snap), [1]).startswith("Semua 2 pos Normal")


def test_summary_and_brief_render_without_any_data():
    snap = _snap({"A": [100.0]}, {})
    snap = {**snap, "levels": snap["levels"].iloc[0:0]}
    cells = app._summary(snap, [], [], AS_OF)
    assert len(cells) == 5
    sub, body = app._brief(snap, [], [], AS_OF)
    assert sub.startswith("Tidak ada pos")


def test_brief_lists_stations_needing_attention_with_reason_and_action():
    snap = _snap({"A": [200.0, 260.0], "B": [100.0, 100.0]}, {"A": {1: 280.0}, "B": {1: 100.0}})
    sub, body = app._brief(snap, _rows(snap), [1], AS_OF)
    assert sub.startswith("1 dari 2 pos perlu perhatian")
    item = str(body[1])
    assert "Siaga 3 → Siaga 2 pada +1 jam" in item and app.REPORT["tindakan"][2] in item
