import pandas as pd
import pytest

from rainfall.frames import (candidate_points, cell_column, date_chunks, dedupe_cells, drop_future,
                             merge_incremental, parse_cell_column, responses_to_frame,
                             select_top_cells)


def test_candidate_points_cover_box_inclusive():
    pts = candidate_points(-6.8, -6.7, 106.6, 106.7, 0.05)
    assert len(pts) == 9
    assert pts[0] == (-6.8, 106.6)
    assert pts[-1] == (-6.7, 106.7)


def test_dedupe_cells_merges_points_snapped_to_same_cell():
    cells = dedupe_cells([(-6.64323, 106.78992), (-6.643233, 106.789921), (-6.43234, 106.82313)])
    assert cells == [(-6.6432, 106.7899), (-6.4323, 106.8231)]


@pytest.mark.parametrize("lat, lon", [(-6.6432, 106.7899), (-6.1, 107.0), (6.25, -0.5)])
def test_cell_column_roundtrip(lat, lon):
    name = cell_column(lat, lon)
    assert name.replace("_", "").isalnum()  # aman sebagai nama kolom BigQuery
    assert parse_cell_column(name) == (lat, lon)


def test_cell_column_format():
    assert cell_column(-6.6432, 106.7899) == "rain_s6_6432_e106_7899"


def test_parse_cell_column_rejects_other_columns():
    with pytest.raises(ValueError):
        parse_cell_column("Bendung Katulampa")


def test_date_chunks_split_inclusive_range():
    assert date_chunks("2024-01-01", "2024-01-10", 4) == [
        ("2024-01-01", "2024-01-04"), ("2024-01-05", "2024-01-08"), ("2024-01-09", "2024-01-10")]
    assert date_chunks("2024-01-01", "2024-01-01", 366) == [("2024-01-01", "2024-01-01")]


def _resp(values, start="2024-01-01T00:00"):
    times = pd.date_range(start, periods=len(values), freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    return {"latitude": 0, "longitude": 0, "hourly": {"time": times, "precipitation": values}}


def test_responses_to_frame_one_column_per_cell():
    cells = [(-6.6432, 106.7899), (-6.4323, 106.8231)]
    df = responses_to_frame([_resp([0.0, 1.5, None]), _resp([2.0, 0.0, 0.1])], cells, "precipitation")

    assert df.index.name == "datetime"
    assert df.index[0] == pd.Timestamp("2024-01-01 00:00")
    assert df.columns.tolist() == [cell_column(*c) for c in cells]
    assert df.iloc[1, 0] == 1.5
    assert pd.isna(df.iloc[2, 0])


def test_responses_to_frame_rejects_count_mismatch():
    with pytest.raises(ValueError):
        responses_to_frame([_resp([0.0])], [(-6.6, 106.8), (-6.5, 106.8)], "precipitation")


def test_drop_future_keeps_up_to_current_hour():
    df = pd.DataFrame({"r": range(5)}, index=pd.date_range("2024-01-01 10:00", periods=5, freq="h"))
    out = drop_future(df, pd.Timestamp("2024-01-01 12:40"))
    assert out.index[-1] == pd.Timestamp("2024-01-01 12:00")


def test_merge_incremental_replaces_from_start_and_keeps_columns():
    idx_old = pd.date_range("2024-01-01", periods=72, freq="h", name="datetime")
    existing = pd.DataFrame({"rain_a": 1.0, "rain_b": 1.0}, index=idx_old)
    idx_new = pd.date_range("2024-01-02", periods=48, freq="h", name="datetime")
    new = pd.DataFrame({"rain_b": 2.0, "rain_a": 2.0, "rain_c": 9.0}, index=idx_new)
    merged = merge_incremental(existing, new, "2024-01-02")

    assert merged.index.is_unique
    assert merged.columns.tolist() == ["rain_a", "rain_b"]
    assert merged.loc["2024-01-01 23:00", "rain_a"] == 1.0
    assert merged.loc["2024-01-02 00:00", "rain_a"] == 2.0
    assert merged.index[-1] == pd.Timestamp("2024-01-03 23:00")


def test_select_top_cells_unions_top_n_per_station():
    a, b, c = cell_column(-6.7, 106.9), cell_column(-6.5, 106.8), cell_column(-6.2, 106.6)
    ranking = pd.DataFrame([
        {"station": "S1", "cell": a, "corr": 0.6},
        {"station": "S1", "cell": b, "corr": 0.4},
        {"station": "S1", "cell": c, "corr": 0.1},
        {"station": "S2", "cell": b, "corr": 0.5},
        {"station": "S2", "cell": c, "corr": float("nan")},
        {"station": "S2", "cell": a, "corr": 0.2},
    ])
    assert select_top_cells(ranking, 1) == [(-6.7, 106.9), (-6.5, 106.8)]
    assert select_top_cells(ranking, 2) == [(-6.7, 106.9), (-6.5, 106.8)]
    assert select_top_cells(ranking, 3) == [(-6.7, 106.9), (-6.5, 106.8), (-6.2, 106.6)]
