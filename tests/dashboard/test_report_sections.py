import pandas as pd

from dashboard.app import REPORT_CFG
from dashboard.data import STATIONS
from dashboard.demo import snapshot
from dashboard.figures import station_rows
from dashboard.report import report_content
from dashboard.report_sections import clock, join, status_phrase, status_short

AS_OF = pd.Timestamp("2026-11-17 21:00")


def _demo():
    snap = snapshot(AS_OF)
    rows = station_rows(snap["levels"], snap["forecast"], STATIONS, 10.0)
    return report_content(snap, rows, [1, 3, 12], AS_OF, "x", REPORT_CFG)


def test_wording_helpers():
    assert status_phrase(1) == "Siaga 1 (Awas)" and status_phrase(2) == "Siaga 2" and status_phrase(4) == "Normal"
    assert status_short(1) == "Awas, Siaga 1" and status_short(2) == "Siaga 2"
    assert join(["A"]) == "A" and join(["A", "B"]) == "A dan B" and join(["A", "B", "C"]) == "A, B, dan C"
    assert clock(AS_OF, AS_OF) == "21:00" and clock(AS_OF + pd.Timedelta(hours=4), AS_OF) == "01:00 (18 Nov)"


def test_sections_are_one_per_river_with_a_status_worst_first():
    doc = _demo()
    assert [s["title"] for s in doc["sections"]] == ["Ciliwung", "Kali Krukut", "Kali Pesanggrahan"]
    ciliwung = doc["sections"][0]
    assert [st["label"] for st in ciliwung["stations"]] == ["Katulampa", "Depok"]  # hulu ke hilir, grafik bertumpuk
    assert [lane["label"] for lane in ciliwung["arrivals"]["lanes"]] == ["Katulampa", "Depok"]
    assert ciliwung["arrivals"]["rows"][0]["kecamatan"] == "Jagakarsa"
    assert {w["label"] for w in doc["watch"]} == {"Angke Hulu", "Waduk Pluit"}  # Normal, hanya sinyal


def test_narrative_names_status_numbers_times_and_deadlines():
    doc = _demo()
    assert doc["summary"][0].startswith("Pada 17 Nov 2026 pukul 21:00 WIB, 3 dari 8 pos")
    assert "Katulampa (Awas, Siaga 1)" in doc["summary"][0]
    katulampa = doc["sections"][0]["stations"][0]["text"]
    assert katulampa.startswith("Pos Katulampa berstatus Siaga 1 (Awas) dengan TMA 205,0 cm pada pukul 21:00 WIB")
    assert "Kecamatan Jagakarsa sekitar pukul 01:00 (18 Nov)" in doc["sections"][0]["impact"]
    evac = doc["sections"][0]["actions"][0]
    assert evac.startswith("Pos Katulampa Siaga 1 (Awas): Himbau RT/RW evakuasi mandiri")
    assert "Tenggat evakuasi: paling lambat pukul 00:00 (18 Nov) di Jagakarsa" in evac
    assert doc["summary"][-1].startswith("Tindakan paling mendesak: persiapan di Kecamatan Jagakarsa")
