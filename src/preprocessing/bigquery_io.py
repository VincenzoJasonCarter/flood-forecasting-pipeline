"""BigQuery I/O: auth, loading raw features, and writing results back."""

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
