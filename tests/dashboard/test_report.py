from io import BytesIO

import pandas as pd
from pypdf import PdfReader

from dashboard.figures import station_rows
from dashboard.report import (assess, attention, build_report, downstream_times, next_limit, report_content,
                              selection_note, snapshot_as_of, stale_note, trend_cm, upstream, wave_speed_kmh)

AS_OF = pd.Timestamp("2026-01-01 12:00")
COORDS = {"A": {"label": "Alfa", "aliran": "Tengah", "siaga": {3: 20, 2: 25, 1: 30}},
          "B": {"label": "Beta", "aliran": "Tengah", "siaga": {3: 7, 2: 10, 1: 12}},
          "C": {"label": "Gama", "aliran": "Barat", "siaga": {3: 100, 2: 150, 1: 200}}}
CFG = {"unit": "jam", "rise_cm": 10.0, "rain_steps": 24, "trend_steps": 3, "near_limit_cm": 5.0,
       "heavy_rain_mm": 50.0,
       "tindakan": {"pantau": "Pantau.", 3: "Waspada <siap>.", 2: "Siagakan.", 1: "Evakuasi."}}


def _levels():
    idx = pd.date_range(AS_OF - pd.Timedelta(hours=3), AS_OF, freq="h")
    return pd.DataFrame({"A": [1.0, 4.0, 8.0, 13.0], "B": [1.0, 2.0, 3.0, None], "C": [50.0, 50.0, 50.0, 50.0]},
                        index=idx)


def _forecast():
    rows = []
    for station, base in (("A", 20.0), ("B", 5.0), ("C", 50.0)):
        for h in (1, 3):
            rows.append({"model": "gru", "station": station, "horizon": h, "as_of": AS_OF,
                         "forecast_time": AS_OF + pd.Timedelta(hours=h),
                         "predicted_value_cm": base + h if station != "C" else base, "generated_at": AS_OF})
    return pd.DataFrame(rows)


def _snap(rain=None, model=None):
    return {"forecast": _forecast(), "levels": _levels(), "rain": rain, "model": model}


def _rows():
    return station_rows(_levels(), _forecast(), COORDS, rise_cm=10.0)


def _by_station(snap=None):
    return {a["row"]["station"]: a for a in assess(_rows(), snap or _snap(), [1, 3], CFG)}


def test_trend_is_the_change_over_the_last_steps_and_skips_missing_readings():
    assert trend_cm(_levels(), "A", 3) == 12.0 and trend_cm(_levels(), "A", 1) == 5.0
    assert trend_cm(_levels(), "B", 3) == 2.0  # NaN terakhir dilewati
    assert trend_cm(_levels(), "Z", 3) is None


def test_next_limit_is_the_first_limit_above_the_current_status():
    rows = {r["station"]: r for r in _rows()}
    assert next_limit(rows["A"]) == (3, 20, 7.0)  # 13 cm, Normal
    assert next_limit({**rows["A"], "now": 26.0, "status_by_h": {0: 2}}) == (1, 30, 4.0)
    assert next_limit({**rows["A"], "status_by_h": {0: 1}}) is None
    assert next_limit({**rows["A"], "status_by_h": {}}) is None


def test_upstream_lists_earlier_alarming_stations_in_the_same_aliran_only():
    ups = upstream(_rows())
    assert [u["station"] for u in ups["B"]] == ["A"]  # A naik ke Siaga 3
    assert ups["A"] == [] and ups["C"] == []


def test_assess_explains_why_and_picks_the_action_for_the_worst_status():
    a = _by_station()
    assert a["A"]["worst"] == 3 and a["A"]["worst_h"] == 1
    assert any(x.startswith("Diprakirakan naik ke Siaga 3") for x in a["A"]["reasons"])
    assert any("Sudah naik 12.0 cm dalam 3 jam" in x for x in a["A"]["reasons"])
    assert a["A"]["action"] == "Waspada <siap>."
    assert any(x.startswith("Pos hulu di aliran Tengah sedang naik: Alfa Siaga 3") for x in a["B"]["reasons"])


def test_quiet_station_has_no_reasons_and_no_action():
    c = _by_station()["C"]
    assert c["reasons"] == [] and c["action"] is None


def test_heavy_rain_in_the_model_cells_is_a_reason():
    idx = _levels().index
    rain = pd.DataFrame({"rain_s6_1_e106_1": [20.0, 20.0, 20.0, 20.0]}, index=idx)
    c = _by_station(_snap(rain=rain, model={"rain_cells": {"C": ["rain_s6_1_e106_1"]}}))["C"]
    assert c["rain_mm"] == 80.0 and c["action"] == "Pantau."
    assert any("(lebat)" in x for x in c["reasons"])


def _pdf_text(pdf):
    assert pdf.startswith(b"%PDF")
    return " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)


def test_report_content_lists_stations_needing_attention_worst_first():
    doc = report_content(_snap(), _rows(), [1, 3], AS_OF + pd.Timedelta(minutes=10), "x", CFG)
    assert [a["row"]["station"] for a in doc["attention"]] == ["A", "B"]
    assert doc["bullets"][0] == "2 dari 3 pos perlu perhatian."
    assert doc["severest"] == 3 and doc["span"] == "sampai +3 jam"  # A 23 cm > 20, B 8 cm > 7


def test_report_pdf_carries_the_finding_actions_and_sources_with_markup_escaped():
    pdf = build_report(_snap(), _rows(), [1, 3], AS_OF + pd.Timedelta(minutes=10), "Alfa naik <segera>", CFG,
                       sources="Sumber & lisensi")
    text = _pdf_text(pdf)
    for expected in ("Alfa naik <segera>", "Waspada <siap>.", "Sumber & lisensi", "Halaman 1 dari"):
        assert expected in text
    # naskah: ringkasan, satu bagian per sungai, lalu lampiran
    assert (text.index("1. Ringkasan") < text.index("2. Alfa") < text.index("Lampiran A. Status")
            < text.index("Lampiran B. Dasar"))


def test_report_lists_the_downstream_areas_of_stations_needing_attention():
    hilir = {"A": {"sungai": "Kali A", "sampai": "laut",
                   "kelurahan": [["Kel Satu", "Kec Hulu", "Kota"], ["Kel Dua", "Kec Hilir", "Kota"]]}}
    cfg = {**CFG, "hilir": hilir}
    a = {x["row"]["station"]: x for x in assess(_rows(), _snap(), [1, 3], cfg)}
    assert a["A"]["hilir"] == {"Kec Hulu": ["Kel Satu"], "Kec Hilir": ["Kel Dua"]} and a["B"]["hilir"] == {}
    text = _pdf_text(build_report(_snap(), _rows(), [1, 3], AS_OF + pd.Timedelta(minutes=10), "x", cfg))
    # tanpa jarak sungai: kecamatan dan kelurahan tetap terdaftar, hanya tanpa jam tiba
    assert "Kec Hulu" in text and "Kel Dua" in text and "jarak sepanjang sungai belum tersedia" in text
    assert "Wilayah hilir = perkiraan" in text
    assert "Wilayah hilir" not in _pdf_text(build_report(_snap(), _rows(), [1, 3], AS_OF, "x", CFG))


def test_report_warns_when_the_data_is_stale():
    notes = report_content(_snap(), _rows(), [1, 3], AS_OF + pd.Timedelta(hours=5), "x", CFG)["notes"]
    assert notes[0].startswith("Data terakhir 5 jam lalu")
    fresh = report_content(_snap(), _rows(), [1, 3], AS_OF + pd.Timedelta(hours=1), "x", CFG)["notes"]
    assert not any(n.startswith("Data terakhir") for n in fresh)


def test_station_without_a_current_reading_is_flagged_by_its_forecast():
    levels = _levels().assign(C=None)  # sensor C mati sepanjang jendela
    forecast = _forecast()
    forecast.loc[forecast["station"] == "C", "predicted_value_cm"] = 160.0  # Siaga 2
    snap = {**_snap(), "levels": levels, "forecast": forecast}
    rows = station_rows(levels, forecast, COORDS, rise_cm=10.0)
    c = {a["row"]["station"]: a for a in assess(rows, snap, [1, 3], CFG)}["C"]
    assert c["now_level"] is None and c["worst"] == 2
    assert c["reasons"] == ["Diprakirakan naik ke Siaga 2 (Siaga) pada +1 jam: 160.0 cm, TMA sekarang tidak terbaca."]
    assert c["action"] == "Siagakan."
    assert "TMA Pos Gama tidak terbaca" in _pdf_text(build_report(snap, rows, [1, 3], AS_OF, "x", CFG))


def test_attention_is_worst_first_and_skips_quiet_stations():
    assert [a["row"]["station"] for a in attention(assess(_rows(), _snap(), [1, 3], CFG))] == ["A", "B"]


def test_snapshot_as_of_falls_back_to_levels_and_is_none_when_both_are_empty():
    assert snapshot_as_of(_snap()) == AS_OF
    assert snapshot_as_of({**_snap(), "forecast": _forecast().iloc[0:0]}) == AS_OF
    empty = {**_snap(), "forecast": _forecast().iloc[0:0], "levels": _levels().iloc[0:0]}
    assert snapshot_as_of(empty) is None
    assert build_report(empty, [], [], AS_OF, "x", CFG).startswith(b"%PDF")  # tanpa data pun tidak error


def test_stale_note_only_after_two_steps():
    assert stale_note(AS_OF + pd.Timedelta(hours=2), AS_OF, "jam") is None
    assert stale_note(AS_OF + pd.Timedelta(hours=3), AS_OF, "jam").startswith("Data terakhir 3 jam lalu")
    assert stale_note(AS_OF, None, "jam") is None


def test_selection_note_uses_whichever_statistic_was_stored():
    assert selection_note({"selection_metric": "mae", "stat": "median", "stat_value": 1.234}) == \
        "median MAE 1.23 saat seleksi"
    assert selection_note({"selection_metric": "mae", "stat": "mean", "stat_value": 2.0}) == "mean MAE 2.00 saat seleksi"
    assert selection_note({"selection_metric": "mae"}) is None


def test_status_banner_is_an_alert_with_the_worst_status_per_horizon_or_safe_when_all_normal():
    from dashboard.overview import id_text, status_banner
    rows = _rows()
    banner = status_banner(rows, [1, 3], "jam", "Alfa naik 23.5 cm")
    assert banner["kind"] == "alert" and banner["text"] == "Alfa naik 23,5 cm"
    assert [w["label"] for w in banner["worst"]] == ["Sekarang", "+1 jam", "+3 jam"]
    calm = [{**r, "status_by_h": {h: 4 for h in r["status_by_h"]}, "rising": False} for r in rows]
    safe = status_banner(calm, [1, 3], "jam", "x")
    assert safe["kind"] == "safe" and safe["head"].startswith("Aman")
    assert id_text("dari 110.0 cm, 19:00") == "dari 110,0 cm, 19:00"


TEMPUH = {"ruas": ["A", "B"], "lag_jam": 4,
          "tenggat": {2: {"tindakan": "persiapan", "jam": 2}, 1: {"tindakan": "evakuasi", "jam": 1}}}
HILIR_KM = {"A": {"sungai": "Kali A", "sampai": "laut",
                  "kelurahan": [["Kel Satu", "Kec Hulu", "Kota"], ["Kel Dua", "Kec Hilir", "Kota"],
                                ["Kel Tiga", "Kec Hilir", "Kota"]],
                  "kecamatan_km": {"Kec Hulu": 5.0, "Kec Hilir": 25.0}}}


def test_wave_speed_is_the_calibration_reach_over_its_lag():
    assert wave_speed_kmh(TEMPUH, {"A": {"B": 40.0}}) == 10.0
    assert wave_speed_kmh(TEMPUH, {}) is None and wave_speed_kmh(None, {"A": {"B": 40.0}}) is None


def test_downstream_times_are_nearest_first_rounded_down_with_the_sop_deadline():
    event_at = AS_OF + pd.Timedelta(hours=1)
    info = {**HILIR_KM["A"], "kecamatan_km": {"Kec Hilir": 25.0, "Kec Hulu": 5.0, "Tak Terjangkau": None}}
    rows = downstream_times(info, 10.0, 2, event_at, AS_OF, TEMPUH["tenggat"])
    assert [r["kecamatan"] for r in rows] == ["Kec Hulu", "Kec Hilir"]
    hulu, hilir = rows
    assert hulu["kelurahan"] == ["Kel Satu"] and hilir["kelurahan"] == ["Kel Dua", "Kel Tiga"]
    assert hulu["jam"] == 0.5 and hulu["tiba"] == event_at  # 0,5 jam dibulatkan ke bawah
    assert hilir["tiba"] == event_at + pd.Timedelta(hours=2)  # 2,5 jam -> 2
    assert hulu["tenggat"] == {"tindakan": "persiapan", "at": event_at - pd.Timedelta(hours=2), "now": True}
    assert hilir["tenggat"]["at"] == AS_OF + pd.Timedelta(hours=1) and not hilir["tenggat"]["now"]
    # Siaga 3 tanpa tenggat; tanpa jam kejadian (harian) tanpa jam tiba; tanpa kecepatan tanpa baris
    assert downstream_times(info, 10.0, 3, event_at, AS_OF, TEMPUH["tenggat"])[0]["tenggat"] is None
    assert downstream_times(info, 10.0, 2, None, AS_OF, TEMPUH["tenggat"])[0]["tiba"] is None
    assert downstream_times(info, None, 2, event_at, AS_OF, TEMPUH["tenggat"]) == []


def test_assess_propagates_the_worst_status_hour_downstream():
    cfg = {**CFG, "hilir": HILIR_KM, "kmh": 10.0, "tempuh": TEMPUH}
    a = {x["row"]["station"]: x for x in assess(_rows(), _snap(), [1, 3], cfg)}
    assert a["A"]["event_step"] == 1 and a["A"]["event_at"] == AS_OF + pd.Timedelta(hours=1)  # Siaga 3 pada +1
    assert [t["kecamatan"] for t in a["A"]["tempuh"]] == ["Kec Hulu", "Kec Hilir"]
    assert a["A"]["tempuh"][0]["tenggat"] is None  # Siaga 3: SOP tanpa tenggat
    assert a["B"]["tempuh"] == []


def test_report_pdf_has_the_travel_time_table_per_kecamatan():
    forecast = _forecast()
    forecast.loc[forecast["station"] == "A", "predicted_value_cm"] = 27.0  # Siaga 2 dari +1
    snap = {**_snap(), "forecast": forecast}
    rows = station_rows(_levels(), forecast, COORDS, rise_cm=10.0)
    cfg = {**CFG, "hilir": HILIR_KM, "kmh": 10.0, "tempuh": TEMPUH}
    text = _pdf_text(build_report(snap, rows, [1, 3], AS_OF, "x", cfg))
    flat = " ".join(text.split())
    assert "Status diprakirakan naik ke Siaga 2 pada +1 jam, pukul 13:00" in flat
    assert "Perkiraan waktu tiba gelombang" in flat and "Tiba gelombang dari Alfa" in flat  # linimasa + legenda
    assert "Kel Dua, Kel Tiga" in flat and "25,0 km · ~2 jam" in flat and "tiba 15:00" in flat
    assert "persiapan segera" in flat and "persiapan 13:00" in flat  # Kec Hulu 13:00-2 sudah lewat; Kec Hilir 15:00-2
    assert "Tenggat persiapan: segera di Kec Hulu; paling lambat pukul 13:00 di Kec Hilir" in flat
    assert "Waktu tempuh = perkiraan" in flat
    assert "Perkiraan waktu tiba gelombang" not in _pdf_text(build_report(snap, rows, [1, 3], AS_OF, "x", CFG))
