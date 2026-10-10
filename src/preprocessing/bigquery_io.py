"""BigQuery I/O: auth, loading raw features, and writing results back."""

import pandas as pd
from google.cloud import bigquery

from .config import LOCATION, PROJECT_ID, WRITE_DISPOSITION


def authenticate():
    """Autentikasi user Colab. No-op di luar lingkungan Colab."""
    try:
        from google.colab import auth
    except ImportError:
        return
    auth.authenticate_user()


def get_client():
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)


def load_station_features(client, table_id):
    query = f"""
        SELECT *
        FROM `{table_id}`
        ORDER BY datetime
    """
    df_fe = client.query(query).to_dataframe()
    df_fe = df_fe.set_index("datetime")
    return df_fe


def load_rainfall_cells(client, table_id, cells, since=None):
    """Kolom sel `cells` dari tabel hujan (output package rainfall), index
    datetime; `since` membatasi ke jam >= since (dipakai serving)."""
    columns = ", ".join(f"`{c}`" for c in cells)
    query = f"SELECT datetime, {columns} FROM `{table_id}`"
    params = []
    if since is not None:
        query += " WHERE datetime >= @since"
        params.append(bigquery.ScalarQueryParameter("since", "DATETIME", pd.Timestamp(since).to_pydatetime()))
    query += " ORDER BY datetime"
    df = client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
    df = df.set_index("datetime")
    if df.index.tz is not None:  # kolom TIMESTAMP -> naive, nilai jam tetap
        df.index = df.index.tz_convert(None)
    return df


def load_df(client, df, table_id, schema=None):
    job_config = bigquery.LoadJobConfig(write_disposition=WRITE_DISPOSITION)
    if schema is not None:
        job_config.schema = schema
    else:
        job_config.autodetect = True
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # tunggu selesai
    tbl = client.get_table(table_id)
    print(f"  {table_id}: {tbl.num_rows:,} rows")
