"""Writing/reading the rainfall frame to a local parquet file and BigQuery."""

import logging

import pandas as pd
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from bq import log_table_size, make_client, run_query, to_naive_datetime_index

from .config import LOCATION, PROJECT_ID

logger = logging.getLogger(__name__)


def get_client():
    return make_client(PROJECT_ID, LOCATION)


def load_parquet(path):
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    return None if df.empty else df


def save_parquet(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    logger.info("Saved: %s %s", path, df.shape)


def load_rainfall(client, table_id):
    """Baca seluruh tabel hujan (index datetime). None kalau belum ada/kosong."""
    try:
        df = run_query(client, "common/select_all_ordered", table=table_id)
    except NotFound:
        return None
    if df.empty:
        return None
    return to_naive_datetime_index(df)


def save_rainfall(client, df, table_id):
    """Timpa seluruh tabel (WRITE_TRUNCATE, atomik)."""
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", autodetect=True)
    job = client.load_table_from_dataframe(df.reset_index(), table_id, job_config=job_config)
    job.result()
    log_table_size(client, table_id)
