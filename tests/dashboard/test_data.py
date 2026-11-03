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
