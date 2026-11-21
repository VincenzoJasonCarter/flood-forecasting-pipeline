"""Shared BigQuery helpers: client factory, query runner, timestamp normalisation."""

import json
import logging
import os

from google.cloud import bigquery

from query_loader import load_query

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_S = 600


def authenticate():
    """Autentikasi user Colab. No-op di luar lingkungan Colab."""
    try:
        from google.colab import auth
    except ImportError:
        return
    auth.authenticate_user()


def make_client(project, location):
    # Vercel tidak punya ADC: service-account JSON dikirim lewat env GCP_SERVICE_ACCOUNT_JSON.
    raw = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(
            json.loads(raw), scopes=["https://www.googleapis.com/auth/bigquery"])
        return bigquery.Client(project=project, location=location, credentials=credentials)
    return bigquery.Client(project=project, location=location)


def scalar_param(name, type_, value):
    """Query parameter bertipe; `value=None` dikirim sebagai NULL."""
    return bigquery.ScalarQueryParameter(name, type_, value)


def run_query(client, name, *, table, columns=None, params=None, timeout=QUERY_TIMEOUT_S):
    """Jalankan queries/{name}.sql dan kembalikan hasilnya sebagai DataFrame."""
    sql = load_query(name, table=table, columns=columns)
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    return client.query(sql, job_config=job_config).result(timeout=timeout).to_dataframe()


def to_naive_datetime_index(df):
    """Index `datetime`, tanpa tz. Kolom TIMESTAMP kembali sebagai UTC tz-aware;
    dibuat naive (nilai jamnya tidak berubah) supaya cocok dengan index hasil crawl."""
    df = df.set_index("datetime")
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    return df


def log_table_size(client, table_id):
    logger.info("%s: %s rows", table_id, f"{client.get_table(table_id).num_rows:,}")
