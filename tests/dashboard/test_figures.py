import pandas as pd

from dashboard.data import STATIONS
from dashboard.figures import (HILIR, HILIR_FILL, KECAMATAN, LEVEL, REGIONS, SIAGA_COLOR, SUNGAI, gauge,
                               hilir_kecamatan, map_figure, rain_cell_coords, rain_totals, siaga_level, station_figure,
                               station_rain, station_rows)

REGIONS_TEST = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "Kota Uji"},
    "geometry": {"type": "MultiPolygon", "coordinates": [[[[106.7, -6.1], [107.0, -6.1], [107.0, -6.45], [106.7, -6.45],
                                                          [106.7, -6.1]]]]}}]}
AS_OF = pd.Timestamp("2026-01-01 12:00")
COORDS = {"A": {"label": "Alfa", "lat": -6.2, "lon": 106.8, "siaga": {3: 20, 2: 25, 1: 30}},
          "B": {"label": "Beta", "side": "left", "lat": -6.4, "lon": 106.9, "siaga": {3: 7, 2: 10, 1: 12}}}


def _levels():
    idx = pd.date_range(AS_OF - pd.Timedelta(hours=3), AS_OF, freq="h")
    return pd.DataFrame({"A": [10.0, 11.0, 12.0, 13.0], "B": [1.0, 2.0, 3.0, None]}, index=idx)


def _forecast():
    rows = []
    for station, base in (("A", 20.0), ("B", 5.0)):
        for h in (1, 3):
            rows.append({"model": "gru", "station": station, "horizon": h, "as_of": AS_OF,
                         "forecast_time": AS_OF + pd.Timedelta(hours=h),
                         "predicted_value_cm": base + h, "generated_at": AS_OF})
    return pd.DataFrame(rows)


def _trace(fig, name):
    return next((t for t in fig.data if t.name == name), None)


def test_figure_has_actual_and_forecast_anchored_at_as_of():
    fig = station_figure(_levels(), _forecast(), "A")
    actual, forecast = _trace(fig, "Aktual"), _trace(fig, "Prakiraan")
    assert list(actual.y) == [10.0, 11.0, 12.0, 13.0]
    assert forecast.x[0] == AS_OF and forecast.y[0] == 13.0  # disambung dari titik aktual
    assert list(forecast.y[1:]) == [21.0, 23.0]


def test_figure_fills_the_actual_area_down_to_the_axis_bottom():
    fig = station_figure(_levels(), _forecast(), "A")
    base, actual = _trace(fig, "Dasar"), _trace(fig, "Aktual")
    assert actual.fill == "tonexty" and set(base.y) == {fig.layout.yaxis.range[0]}


def test_figure_without_forecast_for_station_has_only_actual():
    fig = station_figure(_levels(), _forecast().iloc[0:0], "A")
    assert _trace(fig, "Prakiraan") is None and _trace(fig, "Aktual") is not None


def test_station_rows_use_last_non_nan_level_and_peak_change_from_displayed_values():
    rows = {r["station"]: r for r in station_rows(_levels(), _forecast(), COORDS, rise_cm=10.0)}
    a, b = rows["A"], rows["B"]
    assert a["now"] == 13.0 and a["forecasts"] == {1: 21.0, 3: 23.0}
    assert (a["peak"], a["peak_h"], a["change"], a["rising"]) == (23.0, 3, 10.0, True)  # 23.0 - 13.0, tepat di ambang
    assert b["now"] == 3.0  # NaN terakhir dilewati
    assert b["change"] == 5.0 and b["rising"] is False  # 8.0 - 3.0 < 10


def test_station_rows_rising_per_horizon():
    rows = {r["station"]: r for r in station_rows(_levels(), _forecast(), COORDS, rise_cm=10.0)}
    assert rows["A"]["rising_by_h"] == {1: False, 3: True}  # 21-13=8 ; 23-13=10 tepat di ambang
    assert rows["B"]["rising_by_h"] == {1: False, 3: False}


def test_station_rows_threshold_and_coords():
    rows = {r["station"]: r for r in station_rows(_levels(), _forecast(), COORDS, rise_cm=6.0)}
    assert rows["A"]["rising"] and not rows["B"]["rising"]
    assert (rows["B"]["label"], rows["B"]["side"], rows["B"]["lat"]) == ("Beta", "left", -6.4)
    assert rows["A"]["side"] == "right"


def test_station_rows_without_forecast_keep_stations_that_have_coordinates():
    rows = station_rows(_levels(), _forecast().iloc[0:0], COORDS)
    assert [r["station"] for r in rows] == ["A", "B"]
    assert all(r["peak"] is None and r["change"] is None and not r["rising"] for r in rows)


def test_station_rows_without_coordinates_are_listed_but_not_placed():
    rows = station_rows(_levels(), _forecast(), {})
    assert [r["station"] for r in rows] == ["A", "B"] and rows[0]["lat"] is None


def _pos(fig):
    return [t for t in fig.data if t.name == "Pos"]


def test_map_figure_draws_the_regions_and_one_marker_per_station_and_rings_the_selected_one():
    rows = station_rows(_levels(), _forecast(), COORDS, rise_cm=10.0)
    fig = map_figure(rows, "A", regions=REGIONS_TEST)
    assert sorted(c for t in _pos(fig) for c in t.customdata) == ["A", "B"]
    assert [t.name for t in fig.data if t.fill == "toself"] == ["Kota Uji"]
    assert len([t for t in fig.data if t.name == "Terpilih"]) == 1


def test_map_figure_puts_a_station_south_of_the_map_on_its_bottom_edge_with_the_distance():
    rows = station_rows(_levels(), _forecast(), {**COORDS, "B": {**COORDS["B"], "lat": -6.6}})
    fig = map_figure(rows, "A", regions=REGIONS_TEST)
    texts = [x.strip() for t in _pos(fig) for x in t.text]
    assert any(x.startswith("Beta ↓") and x.endswith("km") for x in texts)
    assert min(y for t in _pos(fig) for y in t.y) < -6.45  # di bawah wilayah (batas bawah -6.45)


def test_siaga_level_needs_to_exceed_the_limit_and_missing_data_is_none():
    limits = {3: 100, 2: 150, 1: 200}
    assert [siaga_level(v, limits) for v in (100, 100.1, 150, 150.1, 200, 200.1)] == [4, 3, 3, 2, 2, 1]
    assert siaga_level(None, limits) is None and siaga_level(50, {}) is None


def test_station_rows_status_per_horizon_with_zero_as_now():
    rows = {r["station"]: r for r in station_rows(_levels(), _forecast(), COORDS)}
    assert rows["A"]["status_by_h"] == {0: 4, 1: 3, 3: 3}  # 13 ; 21 ; 23 terhadap 20/25/30
    assert rows["B"]["status_by_h"] == {0: 4, 1: 4, 3: 3}  # 3 ; 6 ; 8 terhadap 7/10/12
    assert station_rows(_levels(), _forecast(), {})[0]["status_by_h"] == {}  # tanpa ambang: tanpa status


def test_map_figure_colours_by_siaga_status_at_selected_horizon():
    rows = station_rows(_levels(), _forecast(), COORDS)
    colours = lambda h: {c: t.marker.color[i] for t in _pos(map_figure(rows, "A", horizon=h, regions=REGIONS_TEST))  # noqa: E731
                         for i, c in enumerate(t.customdata)}
    assert colours(0) == {"A": SIAGA_COLOR[4], "B": SIAGA_COLOR[4]}
    assert colours(1) == {"A": SIAGA_COLOR[3], "B": SIAGA_COLOR[4]}


def test_bundled_regions_are_the_five_jakarta_cities_and_their_upstream_neighbours():
    names = [f["properties"]["name"] for f in REGIONS["features"]]
    assert names == ["Jakarta Utara", "Jakarta Barat", "Jakarta Pusat", "Jakarta Selatan", "Jakarta Timur", "Depok",
                     "Tangerang", "Tangerang Selatan"]


def test_bundled_hilir_covers_every_configured_station_with_known_kecamatan_and_rivers():
    kecamatan = {f["properties"]["name"] for f in KECAMATAN["features"]}
    rivers = {f["properties"]["name"] for f in SUNGAI["features"]}
    assert len(kecamatan) == 42  # DKI daratan, tanpa Kepulauan Seribu
    assert set(STATIONS) == set(HILIR)
    for station, info in HILIR.items():
        assert info["kelurahan"] and info["sungai"] in rivers, station
        assert set(hilir_kecamatan(station)) <= kecamatan, station
    # tiap pos hulu di dalam peta punya alur putus-putus ke sungainya; Katulampa (di luar peta) tidak
    hulu = {f["properties"]["pos"] for f in SUNGAI["features"] if "pos" in f["properties"]}
    assert hulu == set(STATIONS) - {"Bendung Katulampa", "Waduk Pluit"}


def _square(name, x, y, kind="MultiPolygon"):
    ring = [[x, y], [x + 0.05, y], [x + 0.05, y - 0.05], [x, y - 0.05], [x, y]]
    return {"type": "Feature", "properties": {"name": name}, "geometry": {"type": kind, "coordinates": [[ring]]}}


KEC_TEST = {"type": "FeatureCollection", "features": [_square("Hulu", 106.8, -6.3), _square("Hilir", 106.8, -6.2),
                                                       _square("Lain", 106.9, -6.2)]}
SUNGAI_TEST = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"name": "Kali A"},
     "geometry": {"type": "LineString", "coordinates": [[106.82, -6.34], [106.82, -6.16]]}},
    {"type": "Feature", "properties": {"name": "Kali B"},
     "geometry": {"type": "MultiLineString", "coordinates": [[[106.92, -6.3], [106.92, -6.2]]]}},
    {"type": "Feature", "properties": {"name": "Kali A", "pos": "A"},
     "geometry": {"type": "LineString", "coordinates": [[106.83, -6.40], [106.82, -6.34]]}}]}
HILIR_TEST = {"A": {"sungai": "Kali A", "sampai": "laut",
                    "kelurahan": [["K1", "Hulu", "Kota"], ["K2", "Hilir", "Kota"], ["K3", "Hilir", "Kota"]]}}


def test_hilir_kecamatan_groups_kelurahan_upstream_first_and_is_empty_for_unknown_stations():
    assert hilir_kecamatan("A", HILIR_TEST) == {"Hulu": ["K1"], "Hilir": ["K2", "K3"]}
    assert hilir_kecamatan("B", HILIR_TEST) == {}


def test_map_figure_shades_the_selected_station_downstream_kecamatan_and_its_river():
    rows = station_rows(_levels(), _forecast(), COORDS)
    fig = map_figure(rows, "A", regions=REGIONS_TEST, kecamatan=KEC_TEST, sungai=SUNGAI_TEST, hilir=HILIR_TEST)
    shaded = [t for t in fig.data if t.fillcolor == HILIR_FILL]
    assert [t.name for t in shaded] == ["Hilir Hulu", "Hilir Hilir"]
    assert "K2, K3" in shaded[1].text and shaded[1].hoveron == "fills"
    assert _trace(fig, "Sungai Kali A").line.color == LEVEL and _trace(fig, "Sungai Kali B").line.color != LEVEL
    assert _trace(fig, "Hulu A").line.color == LEVEL and _trace(fig, "Hulu A").line.dash == "dot"
    assert _trace(fig, "Sungai Kali A").line.dash == "solid"
    other = map_figure(rows, "B", regions=REGIONS_TEST, kecamatan=KEC_TEST, sungai=SUNGAI_TEST, hilir=HILIR_TEST)
    assert not [t for t in other.data if t.fillcolor == HILIR_FILL]
    assert _trace(other, "Kecamatan") is not None


def _marks(fig):
    return [sh for sh in fig.layout.shapes if sh.xref == "paper" and sh.x0 == 1.0]


def test_station_figure_marks_only_nearby_siaga_limits_at_the_right_edge():
    marks = _marks(station_figure(_levels(), _forecast(), "A", limits={3: 20, 2: 25, 1: 500}))
    assert [m.y0 for m in marks] == [20, 25]  # 500 terlalu jauh di atas data
    assert not _marks(station_figure(_levels(), _forecast(), "A"))


def test_station_figure_colours_forecast_points_by_status_and_labels_only_the_end():
    fig = station_figure(_levels(), _forecast(), "A", limits={3: 20, 2: 22.5, 1: 500})
    forecast = _trace(fig, "Prakiraan")
    assert list(forecast.marker.color)[1:] == [SIAGA_COLOR[3], SIAGA_COLOR[2]]  # 21 -> Siaga 3, 23 -> Siaga 2
    assert list(forecast.text) == ["", "", "+3 jam · 23.0 cm"]


def test_station_figure_uses_indonesian_time_ticks():
    ticks = station_figure(_levels(), _forecast(), "A").layout.xaxis.ticktext
    assert ticks and all(t.endswith(":00") or " " in t for t in ticks)


def test_map_figure_skips_stations_without_coordinates():
    rows = station_rows(_levels(), _forecast(), {})
    assert not _pos(map_figure(rows, "A", regions=REGIONS_TEST))


def _rain():
    idx = pd.date_range(AS_OF - pd.Timedelta(hours=3), AS_OF, freq="h")
    return pd.DataFrame({"rain_s6_4323_e106_6723": [0.0, 1.0, 2.0, 3.0],
                         "rain_s6_5026_e106_7618": [4.0, 0.0, 0.0, 0.0]}, index=idx)


def test_rain_cell_coords_parse_the_column_name():
    assert rain_cell_coords("rain_s6_4323_e106_6723") == (-6.4323, 106.6723)
    assert rain_cell_coords("Pos Depok") is None


def test_rain_totals_sum_the_last_steps_per_cell():
    assert rain_totals(_rain(), steps=2).to_dict() == {"rain_s6_4323_e106_6723": 5.0, "rain_s6_5026_e106_7618": 0.0}
    assert rain_totals(None).empty


def test_station_rain_averages_the_model_cells_and_skips_unknown_ones():
    rain = station_rain(_rain(), ["rain_s6_4323_e106_6723", "rain_s6_5026_e106_7618", "rain_missing"])
    assert list(rain) == [2.0, 0.5, 1.0, 1.5]
    assert station_rain(_rain(), None) is None and station_rain(None, ["x"]) is None


def test_station_rows_follow_the_config_order():
    coords = {"B": COORDS["B"], "A": COORDS["A"]}
    assert [r["station"] for r in station_rows(_levels(), _forecast(), coords)] == ["B", "A"]


def test_station_figure_widens_the_axis_down_to_nearby_limits_below_the_data():
    levels = pd.DataFrame({"P": [-20.0, -5.0, 10.0, 0.0]}, index=_levels().index)  # mis. Waduk Pluit
    fig = station_figure(levels, _forecast().iloc[0:0], "P", limits={3: -55, 2: 0, 1: 45})
    bottom, top = fig.layout.yaxis.range
    assert [m.y0 for m in _marks(fig)] == [-55, 0, 45]
    assert all(bottom < m.y0 < top for m in _marks(fig))
    far = station_figure(levels, _forecast().iloc[0:0], "P", limits={3: -500, 2: 0})
    assert [m.y0 for m in _marks(far)] == [0]  # batas jauh di bawah tidak ditandai


def test_gauge_places_now_and_peak_against_the_station_own_siaga_bands():
    row = station_rows(_levels(), _forecast(), COORDS)[0]  # A: TMA 13, prakiraan 21 dan 23, batas 20/25/30
    g = gauge(row)
    assert [lvl for lvl, _, _ in g["zones"]] == [4, 3, 2, 1]
    assert g["zones"][0][1] == 0.0 and g["zones"][-1][2] == 100.0
    assert all(a[2] == b[1] for a, b in zip(g["zones"], g["zones"][1:]))  # zona bersambung tanpa celah
    assert 0 < g["now"] < g["zones"][1][1] < g["peak"] < g["zones"][2][1]  # 13 di Normal, puncak 23 di Siaga 3
    assert gauge({**row, "limits": {}}) is None


def test_station_figure_over_a_year_marks_months_and_draws_a_straight_line():
    idx = pd.date_range(AS_OF - pd.Timedelta(days=365), AS_OF, freq="h")
    levels = pd.DataFrame({"A": [10.0] * len(idx)}, index=idx)
    fig = station_figure(levels, _forecast().iloc[0:0], "A")
    assert _trace(fig, "Aktual").line.shape == "linear"
    assert list(fig.layout.xaxis.ticktext)[:2] == ["Feb", "Mar"] and "Jan 2026" in fig.layout.xaxis.ticktext
