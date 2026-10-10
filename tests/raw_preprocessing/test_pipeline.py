import pandas as pd
import pytest

from raw_preprocessing.config import CALENDAR_COLS
from raw_preprocessing.pipeline import _merge_incremental, _resume_start, run


def test_run_rejects_unknown_granularity_before_crawling():
    # Raises before get_token/crawl_range, so no token or network is needed.
    with pytest.raises(ValueError, match="granularity"):
        run(granularity="weekly")


def _frame(days, value, start="2026-01-01"):
    idx = pd.date_range(start, periods=days, freq="D", name="datetime")
    df = pd.DataFrame({"Station A": float(value)}, index=idx)
    for col in CALENDAR_COLS:
        df[col] = 0
    return df


def test_resume_start_none_when_output_missing(tmp_path):
    assert _resume_start(tmp_path / "nope.parquet", 3) == (None, None)


def test_resume_start_goes_back_overlap_days(tmp_path):
    path = tmp_path / "out.parquet"
    _frame(10, 1).to_parquet(path)  # 2026-01-01 .. 2026-01-10
    existing, start = _resume_start(path, 3)
    assert len(existing) == 10
    assert start == "2026-01-07"


def test_merge_incremental_keeps_context_day_and_replaces_rest():
    existing = _frame(10, 1)  # s/d 2026-01-10
    new = _frame(7, 2, start="2026-01-07")  # crawl ulang dari 01-07, s/d 01-13
    merged = _merge_incremental(existing, new, "2026-01-07")

    assert merged.index.is_unique
    assert merged.index.min() == pd.Timestamp("2026-01-01")
    assert merged.index.max() == pd.Timestamp("2026-01-13")
    assert merged.loc["2026-01-07", "Station A"] == 1  # hari konteks: tetap lama
    assert merged.loc["2026-01-08", "Station A"] == 2  # diganti hasil baru
    assert merged.columns[-len(CALENDAR_COLS):].tolist() == CALENDAR_COLS


def _hourly_frame(hours, value, start="2026-01-01 00:00"):
    idx = pd.date_range(start, periods=hours, freq="h", name="datetime")
    df = pd.DataFrame({"Station A": float(value), "Station B": float(value)}, index=idx)
    for col in CALENDAR_COLS:
        df[col] = 0
    return df


def test_merge_incremental_hourly_revises_stale_tail_hours():
    # Output lama s/d 2026-01-10 14:00; jam terakhir Station B masih NaN (laporan telat).
    existing = _hourly_frame(9 * 24 + 15, 1)
    existing.loc["2026-01-10 12:00":, "Station B"] = float("nan")
    # Crawl ulang dari 2026-01-07 00:00 s/d 2026-01-11 05:00, sekarang lengkap.
    new = _hourly_frame(4 * 24 + 6, 2, start="2026-01-07 00:00")
    merged = _merge_incremental(existing, new, "2026-01-07")

    assert merged.index.is_unique
    assert len(merged) == 10 * 24 + 6  # 2026-01-01 00:00 .. 2026-01-11 05:00, tanpa lubang
    assert (merged.loc["2026-01-07", "Station A"] == 1).all()  # hari konteks: tetap lama
    assert merged.loc["2026-01-08 00:00", "Station A"] == 2
    assert merged.loc["2026-01-10 12:00":"2026-01-10 14:00", "Station B"].eq(2).all()  # NaN lama terkoreksi


def test_merge_incremental_drops_columns_not_in_existing():
    existing = _hourly_frame(48, 1)
    new = _hourly_frame(48, 2, start="2026-01-01 00:00").assign(**{"Station C": 5.0})
    merged = _merge_incremental(existing, new, "2026-01-01")

    assert "Station C" not in merged.columns
    assert merged.columns.tolist() == existing.columns.tolist()
