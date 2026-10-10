import pandas as pd
import pytest

import rainfall.pipeline as rp
from rainfall.client import RateLimited
from rainfall.frames import cell_column

CELLS = [(-6.7, 106.9)]
NOW = pd.Timestamp("2024-02-01")


def _frame(start, hours=24):
    idx = pd.date_range(start, periods=hours, freq="h", name="datetime")
    return pd.DataFrame({cell_column(*CELLS[0]): 1.0}, index=idx)


def _fetch_one_chunk_then(exc):
    def fake(session, throttle, cells, start, end):
        yield _frame("2024-01-01")
        raise exc
    return fake


@pytest.fixture
def saved(monkeypatch):
    out = {}
    monkeypatch.setattr(rp, "get_client", lambda: None)
    monkeypatch.setattr(rp, "save_parquet", lambda df, path: out.update(parquet=df))
    monkeypatch.setattr(rp, "save_rainfall", lambda client, df, table: out.update(bq=(df, table)))
    return out


def test_run_saves_completed_chunks_then_reraises_other_errors(monkeypatch, saved):
    monkeypatch.setattr(rp, "fetch_range", _fetch_one_chunk_then(RuntimeError("network down")))
    with pytest.raises(RuntimeError, match="network down"):
        rp.run(start="2024-01-01", end="2024-01-10", write_bq=True, cells=CELLS, table_id="p.d.survey", now=NOW)

    assert len(saved["parquet"]) == 24
    assert saved["bq"][1] == "p.d.survey"


def test_run_stops_quietly_when_quota_runs_out(monkeypatch, saved):
    monkeypatch.setattr(rp, "fetch_range", _fetch_one_chunk_then(RateLimited("Daily API request limit exceeded")))
    df = rp.run(start="2024-01-01", end="2024-01-10", cells=CELLS, now=NOW)

    assert len(df) == 24
    assert len(saved["parquet"]) == 24
    assert "bq" not in saved  # tanpa write_bq


def test_run_writes_nothing_when_first_chunk_fails(monkeypatch, saved):
    def fail(session, throttle, cells, start, end):
        raise RuntimeError("down")
        yield  # generator

    monkeypatch.setattr(rp, "fetch_range", fail)
    with pytest.raises(RuntimeError):
        rp.run(start="2024-01-01", end="2024-01-10", write_bq=True, cells=CELLS, now=NOW)
    assert saved == {}
