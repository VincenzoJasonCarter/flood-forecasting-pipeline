import pytest

from dashboard import data


@pytest.fixture
def cache(monkeypatch):
    monkeypatch.setattr(data, "_cache", {"at": float("-inf"), "value": None, "error": None})
    monkeypatch.setattr(data, "_get_client", lambda: None)
    calls = []

    def query(results):
        def run(_client):
            calls.append(1)
            result = results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(data, "_query_all", run)
    return query, calls


def test_failure_serves_the_last_good_snapshot_and_is_not_retried_within_the_ttl(cache):
    query, calls = cache
    query([{"v": 1}, RuntimeError("bq down")])
    assert data.load_snapshot() == {"v": 1}
    assert data.load_snapshot(force=True) == {"v": 1}  # gagal, snapshot lama tetap disajikan
    assert data.load_snapshot() == {"v": 1} and len(calls) == 2  # kegagalan di-cache, tidak dicoba ulang


def test_failure_without_any_snapshot_raises_until_the_ttl_passes(cache):
    query, calls = cache
    query([RuntimeError("bq down")])
    for _ in range(3):
        with pytest.raises(RuntimeError):
            data.load_snapshot()
    assert len(calls) == 1


def test_history_is_read_once_per_station_and_range_within_the_refresh(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(data, "_history", {})
    monkeypatch.setattr(data, "_get_client", lambda: None)
    calls = []

    def run(_client, name, **kwargs):
        calls.append((name, kwargs["columns"], kwargs["params"][0].value))
        return pd.DataFrame({"datetime": pd.date_range("2026-01-01", periods=3, freq="h")[::-1], "A": [3.0, 2.0, 1.0]})
    monkeypatch.setattr(data, "run_query", run)
    first = data.load_history("A", 720)
    assert list(first["A"]) == [1.0, 2.0, 3.0]  # urut naik
    data.load_history("A", 720)
    data.load_history("A", 8760)
    assert calls == [("dashboard/station_history", ["A"], 720), ("dashboard/station_history", ["A"], 8760)]


def test_with_the_background_refresher_a_stale_snapshot_is_served_without_waiting(cache, monkeypatch):
    query, calls = cache
    query([{"v": 1}, {"v": 2}])
    monkeypatch.setattr(data, "_refresher", {"on": True})
    assert data.load_snapshot() == {"v": 1}  # sebelum ada data, pembacaan pertama tetap ditunggu
    data._cache["at"] = float("-inf")  # lewat umur
    assert data.load_snapshot() == {"v": 1} and len(calls) == 1  # callback tidak memicu BigQuery
    assert data.load_snapshot(force=True) == {"v": 2}  # tombol Muat ulang tetap membaca ulang


def test_background_refresher_warms_long_history_only_beyond_the_snapshot(monkeypatch):
    warmed = []
    monkeypatch.setattr(data, "STATIONS", {"A": {}, "B": {}})
    monkeypatch.setattr(data, "HISTORY_STEPS", 72)
    monkeypatch.setattr(data, "load_history", lambda station, steps: warmed.append((station, steps)))
    data._warm_history({72, 168, 720})
    assert sorted(warmed) == [("A", 168), ("A", 720), ("B", 168), ("B", 720)]
