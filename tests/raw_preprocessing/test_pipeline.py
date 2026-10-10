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
