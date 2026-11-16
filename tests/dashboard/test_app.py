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


def test_overview_builders_render_without_any_data():
    snap = _snap({"A": [100.0]}, {})
    snap = {**snap, "levels": snap["levels"].iloc[0:0]}
    cls, _ = app._banner(snap, [], [])
    assert cls == "banner"
    assert len(app._kpi_cards(snap, [])) == 3
    title, _, _ = app._attention(snap, [], [], AS_OF)
    assert title.startswith("Tidak ada pos")


def test_banner_warns_when_a_station_is_forecast_to_rise_above_normal():
    snap = _snap({"A": [200.0, 260.0], "B": [100.0, 100.0]}, {"A": {1: 280.0}, "B": {1: 100.0}})
    cls, body = app._banner(snap, _rows(snap), [1])
    text = str(body)
    assert cls == "banner alert s2"
    assert "PERINGATAN · SIAGA 2 DALAM 1 JAM" in text and "Alfa naik — Siaga diprakirakan dalam 1 jam" in text


def test_banner_names_the_station_when_it_is_already_the_worst_now():
    snap = _snap({"A": [260.0, 260.0], "B": [100.0, 100.0]}, {"A": {1: 255.0}, "B": {1: 100.0}})
    cls, body = app._banner(snap, _rows(snap), [1])
    assert cls == "banner alert s3"
    assert "PERINGATAN · SIAGA 3 SEKARANG" in str(body) and "Alfa berstatus Waspada" in str(body)


def test_banner_is_safe_when_everything_is_normal_and_lists_the_stations_to_watch():
    snap = _snap({"A": [100.0, 100.0], "B": [100.0, 100.0]}, {"A": {1: 130.0}, "B": {1: 100.0}})
    cls, body = app._banner(snap, _rows(snap), [1])
    text = str(body)
    assert cls == "banner safe" and "Aman — semua pos Normal" in text
    assert "1 pos diprakirakan naik dan perlu dipantau: Alfa." in text


def test_attention_is_titled_by_whether_anything_is_above_normal():
    warn = _snap({"A": [200.0, 260.0], "B": [100.0, 100.0]}, {"A": {1: 280.0}, "B": {1: 100.0}})
    title, _, body = app._attention(warn, _rows(warn), [1], AS_OF)
    assert title == "Perlu tindakan · 1 dari 2 pos"
    assert app.REPORT["tindakan"][2] in str(body) and "menuju Siaga dalam 1 jam" in str(body)
    quiet = _snap({"A": [100.0, 100.0], "B": [100.0, 100.0]}, {"A": {1: 130.0}, "B": {1: 100.0}})
    title, sub, _ = app._attention(quiet, _rows(quiet), [1], AS_OF)
    assert title == "Perlu dipantau · 1 dari 2 pos" and sub.startswith("Semua masih Normal")


def test_matrix_lists_the_worst_station_first_and_marks_the_selected_one():
    snap = _snap({"A": [100.0, 100.0], "B": [100.0, 160.0]}, {"A": {1: 100.0}, "B": {1: 170.0}})
    items = app._matrix(_rows(snap), [1], 0, "A")[1:]
    assert [i.id["station"] for i in items] == ["B", "A"]
    assert [i.className for i in items] == ["mx-row mx-item", "mx-row mx-item sel"]


def test_pick_follows_a_real_click_only(monkeypatch):
    from types import SimpleNamespace
    row = {"type": "row", "station": "B"}
    monkeypatch.setattr(app, "ctx", SimpleNamespace(triggered_id=row, triggered=[{"value": 1}]))
    assert app.pick(None, [1], [None]) == "B"
    monkeypatch.setattr(app, "ctx", SimpleNamespace(triggered_id=row, triggered=[{"value": 0}]))
    assert app.pick(None, [0], [None]) is app.no_update  # baris baru disisipkan ulang, belum diklik
    click = {"points": [{"customdata": "A"}]}
    monkeypatch.setattr(app, "ctx", SimpleNamespace(triggered_id="map", triggered=[{"value": click}]))
    assert app.pick(click, [], []) == "A"


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


def test_station_list_links_each_station_groups_by_aliran_and_marks_the_selected_one():
    snap = _snap({"A": [100.0, 100.0], "B": [100.0, 160.0]}, {"A": {1: 110.0}, "B": {1: 150.0}})
    items = app._station_list(_rows(snap), [1], "B")[1].children
    links = [i for i in items if i.__class__.__name__ == "Link"]
    assert [link.href for link in links] == ["/pos?nama=A", "/pos?nama=B"]
    assert [link.className for link in links] == ["pl-item", "pl-item sel"]
    text = str(items)
    assert "ALIRAN TENGAH" in text and "ALIRAN BARAT" in text
    assert "▲ +10,0" in text and "▼ −10,0" in text and "100,0 cm ke S3" in text and "90,0 cm ke S2" in text


def test_outlook_shows_the_status_itself_and_when_it_gets_worse():
    rows = {r["station"]: r for r in _rows(_snap({"A": [100.0, 260.0], "B": [100.0, 100.0]},
                                                 {"A": {1: 280.0, 3: 100.0}, "B": {1: 100.0, 3: 100.0}}))}
    assert app._outlook(rows["A"], [1, 3]) == (2, "Siaga 2", "pada +1 jam")
    assert app._outlook(rows["B"], [1, 3]) == (4, "Normal", "")


def test_vertical_gauge_keeps_labels_apart_and_marks_the_overshoot():
    snap = _snap({"A": [100.0, 150.0], "B": [100.0, 100.0]}, {"A": {1: 155.0}, "B": {1: 100.0}})
    gauge = app._vgauge(_rows(snap)[0])
    tops = sorted(float(label.style["top"][:-2]) for label in gauge.children[1].children
                  if "vg-label" in label.className and "vg-base" not in label.className)
    assert all(b - a >= app.VG_GAP - 0.01 for a, b in zip(tops, tops[1:]))
    assert "50,0 cm lagi" in str(gauge)


def test_downstream_card_numbers_the_kecamatan_from_upstream_and_builds_the_copy_text(monkeypatch):
    hilir = {"A": {"sungai": "Kali A", "sampai": "laut, lewat Drain X",
                   "kelurahan": [["Kel Satu", "Hulu", "Kota"], ["Kel Dua", "Hilir", "Kota"]]}}
    monkeypatch.setattr(app, "HILIR", hilir)
    row = {**_rows(_snap({"A": [100.0], "B": [100.0]}, {"A": {1: 100.0}, "B": {1: 100.0}}))[0], "station": "A"}
    card, text = app._hilir_card(row)
    assert "Laut · lewat Drain X" in str(card) and "2 kelurahan di 2 kecamatan" in str(card)
    assert text == "Wilayah hilir A (perkiraan):\n1. Kec. Hulu: Kel Satu\n2. Kec. Hilir: Kel Dua"
    assert app._hilir_card({"station": "tidak ada", "label": "x"})[1] == ""


def test_route_puts_the_chart_on_the_overview_and_the_board_on_the_detail_page(monkeypatch):
    snap = _snap({"A": [100.0], "B": [100.0]}, {"A": {1: 100.0}, "B": {1: 100.0}})
    monkeypatch.setattr(app, "_snapshot", lambda force=False: snap)
    monkeypatch.setattr(app, "STATIONS", COORDS)
    monkeypatch.setattr(app, "load_history", lambda *a: snap["levels"])  # halaman langsung terisi: tanpa BigQuery
    page, overview, detail = app.route("/", "")
    assert (overview, detail) == ("nav-link on", "nav-link")
    assert "'chart'" in str(page) and "'range'" in str(page) and "'dt-list'" not in str(page)
    page, overview, detail = app.route("/pos", "?nama=B")
    assert (overview, detail) == ("nav-link", "nav-link on")
    assert "'dt-list'" in str(page) and "'chart'" not in str(page)


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


def test_matrix_column_headers_switch_the_map_horizon_on_a_real_click(monkeypatch):
    from types import SimpleNamespace
    snap = _snap({"A": [100.0], "B": [100.0]}, {"A": {1: 100.0, 3: 100.0}, "B": {1: 100.0, 3: 100.0}})
    head = app._matrix(_rows(snap), [1, 3], 3, "A")[0].children
    assert [b.id["h"] for b in head[1:]] == [0, 1, 3] and head[3].className == "mx-h on"
    monkeypatch.setattr(app, "ctx", SimpleNamespace(triggered_id={"type": "hz", "h": 1}, triggered=[{"value": 1}]))
    assert app.pick_horizon([0, 1, 0]) == 1
    monkeypatch.setattr(app, "ctx", SimpleNamespace(triggered_id={"type": "hz", "h": 1}, triggered=[{"value": 0}]))
    assert app.pick_horizon([0, 0, 0]) is app.no_update
