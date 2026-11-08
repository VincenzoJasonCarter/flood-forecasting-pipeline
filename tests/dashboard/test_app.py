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
    cells, meta = app._summary(snap, [], [], AS_OF)
    assert len(cells) == 3
    assert "Data terakhir" in str(meta) and "Model" in str(meta)
    sub, body = app._brief(snap, [], [], AS_OF)
    assert sub.startswith("Tidak ada pos")


def test_brief_lists_stations_needing_attention_with_reason_and_action():
    snap = _snap({"A": [200.0, 260.0], "B": [100.0, 100.0]}, {"A": {1: 280.0}, "B": {1: 100.0}})
    sub, body = app._brief(snap, _rows(snap), [1], AS_OF)
    assert sub.startswith("1 dari 2 pos perlu perhatian")
    item = str(body[1])
    assert "Siaga 3 → Siaga 2 pada +1 jam" in item and app.REPORT["tindakan"][2] in item


def test_short_range_is_cut_from_the_snapshot_without_reading_history(monkeypatch):
    monkeypatch.setattr(app, "STEP_HOURS", 1)
    monkeypatch.setattr(app, "load_history", lambda *a: pytest.fail("history read for a range the snapshot covers"))
    snap = _snap({"A": [100.0] * 100}, {})
    levels, note = app._chart_levels(snap, "A", "3d")
    assert len(levels) == 72 and note is None


def test_long_range_reads_the_station_history(monkeypatch):
    monkeypatch.setattr(app, "STEP_HOURS", 1)
    calls = []
    long = _snap({"A": [100.0] * 720}, {})["levels"]
    monkeypatch.setattr(app, "load_history", lambda station, steps: calls.append((station, steps)) or long)
    levels, note = app._chart_levels(_snap({"A": [100.0] * 72}, {}), "A", "1m")
    assert calls == [("A", 720)] and len(levels) == 720 and note is None


def test_range_longer_than_the_data_says_since_when(monkeypatch):
    monkeypatch.setattr(app, "STEP_HOURS", 1)
    short = _snap({"A": [100.0] * 200}, {})["levels"]
    monkeypatch.setattr(app, "load_history", lambda station, steps: short)
    _, note = app._chart_levels(_snap({"A": [100.0] * 72}, {}), "A", "1y")
    assert note.startswith("Data baru tersedia sejak")


def test_failed_history_read_falls_back_to_the_snapshot(monkeypatch):
    monkeypatch.setattr(app, "STEP_HOURS", 1)

    def fail(*_):
        raise RuntimeError("bq down")
    monkeypatch.setattr(app, "load_history", fail)
    levels, note = app._chart_levels(_snap({"A": [100.0] * 72}, {}), "A", "1w")
    assert len(levels) == 72 and "gagal dibaca" in note


def test_board_rows_link_to_their_station_and_fill_the_selected_one():
    snap = _snap({"A": [100.0], "B": [100.0]}, {"A": {1: 100.0}, "B": {1: 100.0}})
    links = [item for item in app._board(_rows(snap), [1], 0, "B") if item.__class__.__name__ == "Link"]
    assert [link.href for link in links] == ["/pos?nama=A", "/pos?nama=B"]
    assert [link.className for link in links] == ["bd-row", "bd-row on"]


def test_route_puts_the_chart_on_the_overview_and_the_board_on_the_detail_page(monkeypatch):
    snap = _snap({"A": [100.0], "B": [100.0]}, {"A": {1: 100.0}, "B": {1: 100.0}})
    monkeypatch.setattr(app, "_snapshot", lambda force=False: snap)
    monkeypatch.setattr(app, "STATIONS", COORDS)
    page, overview, detail = app.route("/", "")
    assert (overview, detail) == ("nav-link on", "nav-link")
    assert "'chart'" in str(page) and "'range'" in str(page) and "'board'" not in str(page)
    page, overview, detail = app.route("/pos", "?nama=B")
    assert (overview, detail) == ("nav-link", "nav-link on")
    assert "'board'" in str(page) and "'chart'" not in str(page)


def test_detail_station_comes_from_the_query_and_falls_back_to_the_default():
    snap = _snap({"A": [100.0], "B": [300.0]}, {"A": {1: 100.0}, "B": {1: 300.0}})
    rows = _rows(snap)
    assert app._search_station("?nama=A", rows) == "A"
    assert app._search_station("?nama=Tidak+Ada", rows) == app._search_station("", rows) == "B"


def test_report_downloads_only_on_a_real_click(monkeypatch):
    monkeypatch.setattr(app, "_report", lambda: "pdf")
    assert app.download_report_brief(0) is app.no_update  # tombol baru disisipkan halaman, belum diklik
    assert app.download_report(None) is app.no_update
    assert app.download_report_brief(1) == "pdf" and app.download_report(1) == "pdf"
