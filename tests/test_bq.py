import pandas as pd

import bq


class _FakeResult:
    def __init__(self, df):
        self._df = df

    def to_dataframe(self):
        return self._df


class _FakeJob:
    def __init__(self, df, timeouts):
        self._df, self._timeouts = df, timeouts

    def result(self, timeout=None):
        self._timeouts.append(timeout)
        return _FakeResult(self._df)


class _FakeClient:
    def __init__(self, df):
        self.df, self.calls, self.timeouts = df, [], []

    def query(self, sql, job_config=None):
        self.calls.append((sql, job_config))
        return _FakeJob(self.df, self.timeouts)


def test_run_query_renders_sql_and_passes_parameters():
    expected = pd.DataFrame({"station": ["A"], "weights": [b"x"]})
    client = _FakeClient(expected)

    out = bq.run_query(client, "prediction/torch_weights", table="p.d.lstm_weights_hourly",
                       params=[bq.scalar_param("station", "STRING", "A"),
                               bq.scalar_param("horizon", "INT64", None)])

    sql, job_config = client.calls[0]
    assert "`p.d.lstm_weights_hourly`" in sql
    assert [(p.name, p.value) for p in job_config.query_parameters] == [("station", "A"), ("horizon", None)]
    assert client.timeouts == [bq.QUERY_TIMEOUT_S]
    assert out is expected


def test_to_naive_datetime_index_strips_utc_without_shifting_values():
    df = pd.DataFrame({"datetime": pd.date_range("2025-01-01", periods=3, freq="h", tz="UTC"), "v": [1, 2, 3]})
    out = bq.to_naive_datetime_index(df)
    assert out.index.tz is None
    assert out.index[0] == pd.Timestamp("2025-01-01 00:00")


def test_to_naive_datetime_index_leaves_naive_index_alone():
    df = pd.DataFrame({"datetime": pd.date_range("2025-01-01", periods=2, freq="h"), "v": [1, 2]})
    assert bq.to_naive_datetime_index(df).index[1] == pd.Timestamp("2025-01-01 01:00")
