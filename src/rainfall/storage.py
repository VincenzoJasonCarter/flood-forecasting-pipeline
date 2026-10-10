"""Writing/reading the rainfall frame to a local parquet file and BigQuery."""

import pandas as pd
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from .config import LOCATION, PROJECT_ID


def get_client():
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)


def load_parquet(path):
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    return None if df.empty else df


def save_parquet(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    print(f"Saved: {path} {df.shape}")


def load_rainfall(client, table_id):
    """Baca seluruh tabel hujan (index datetime). None kalau belum ada/kosong."""
    try:
        df = client.query(f"SELECT * FROM `{table_id}` ORDER BY datetime").to_dataframe()
    except NotFound:
        return None
    if df.empty:
        return None
    df = df.set_index("datetime")
    if df.index.tz is not None:  # kolom TIMESTAMP -> naive, nilai jam tetap
        df.index = df.index.tz_convert(None)
    return df


def save_rainfall(client, df, table_id):
    """Timpa seluruh tabel (WRITE_TRUNCATE, atomik)."""
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", autodetect=True)
    job = client.load_table_from_dataframe(df.reset_index(), table_id, job_config=job_config)
    job.result()
    tbl = client.get_table(table_id)
    print(f"  {table_id}: {tbl.num_rows:,} rows")
