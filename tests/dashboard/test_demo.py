import pandas as pd
import pytest

from dashboard.app import REPORT_CFG
from dashboard.data import STATIONS
from dashboard.demo import MARK, SCENARIO, snapshot
from dashboard.figures import station_rows
from dashboard.report import report_content

AS_OF = pd.Timestamp("2026-11-17 21:00")


def _doc():
    snap = snapshot(AS_OF)
    rows = station_rows(snap["levels"], snap["forecast"], STATIONS, 10.0)
    cfg = {**REPORT_CFG, "demo": MARK}
    return report_content(snap, rows, [1, 3, 12], AS_OF, "x", cfg), rows


def test_demo_covers_every_station_and_shows_awas_and_siaga():
    doc, rows = _doc()
    assert set(SCENARIO) == set(STATIONS)
    status = {r["station"]: r["status_by_h"] for r in rows}
    assert status["Bendung Katulampa"][0] == 1 and status["Pos Depok"][3] == 2
    assert status["Pos Cipinang Hulu"][0] == 4


def test_demo_report_is_marked_and_has_travel_times_with_deadlines():
    doc, _ = _doc()
    assert doc["title"].endswith("(DEMO)") and doc["meta"][0] == MARK.upper()
    katulampa = next(a for a in doc["attention"] if a["row"]["station"] == "Bendung Katulampa")
    assert katulampa["tempuh"] and katulampa["tempuh"][0]["tenggat"]["tindakan"] == "evakuasi"


@pytest.mark.parametrize("gaya", ["formal", "pita", "peta"])
def test_demo_report_opens_with_a_one_page_cover_and_numbers_pages_after_it(gaya):
    from io import BytesIO

    from pypdf import PdfReader

    from dashboard.report import build_report

    snap = snapshot(AS_OF)
    rows = station_rows(snap["levels"], snap["forecast"], STATIONS, 10.0)
    cfg = {**REPORT_CFG, "demo": MARK, "sampul": {**REPORT_CFG["sampul"], "gaya": gaya}}
    pdf = build_report(snap, rows, [1, 3, 12], AS_OF, "x", cfg)
    pages = [p.extract_text() for p in PdfReader(BytesIO(pdf)).pages]
    cover = " ".join(pages[0].split())
    for expected in ("pantauan dan prakiraan banjir", MARK.lower(), "katulampa berstatus awas",
                     "tindakan paling mendesak: persiapan di kecamatan jagakarsa", "lpb-20261117-2100",
                     "pemerintah provinsi dki jakarta"):
        assert expected in cover.lower(), expected
    assert "Halaman" not in pages[0]  # sampul tanpa kepala/kaki dan tidak dihitung
    assert pages[1].lstrip().startswith("1. Ringkasan") and f"Halaman 1 dari {len(pages) - 1}" in pages[1]
