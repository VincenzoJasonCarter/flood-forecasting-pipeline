"""BigQuery I/O: auth, loading raw features, and writing results back."""

import logging

import pandas as pd
from google.cloud import bigquery

from bq import authenticate, log_table_size, make_client, run_query, scalar_param, to_naive_datetime_index

from .config import LOCATION, PROJECT_ID, WRITE_DISPOSITION

logger = logging.getLogger(__name__)

__all__ = ["authenticate", "get_client", "load_df", "load_rainfall_cells", "load_station_features"]


def get_client():
    return make_client(PROJECT_ID, LOCATION)


def load_station_features(client, table_id):
    df_fe = run_query(client, "common/select_all_ordered", table=table_id)
    df_fe = df_fe.set_index("datetime")
    return df_fe


def load_rainfall_cells(client, table_id, cells, since=None):
    """Kolom sel `cells` dari tabel hujan (output package rainfall), index
    datetime; `since` membatasi ke jam >= since (dipakai serving)."""
    since = None if since is None else pd.Timestamp(since).to_pydatetime()
    df = run_query(client, "common/rainfall_cells", table=table_id, columns=cells,
                   params=[scalar_param("since", "DATETIME", since)])
    return to_naive_datetime_index(df)


def load_df(client, df, table_id, schema=None):
    job_config = bigquery.LoadJobConfig(write_disposition=WRITE_DISPOSITION)
    if schema is not None:
        job_config.schema = schema
    else:
        job_config.autodetect = True
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # tunggu selesai
    log_table_size(client, table_id)
