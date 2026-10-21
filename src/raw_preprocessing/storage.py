"""Writing the station features to a local parquet file and/or BigQuery."""

import logging

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from bq import log_table_size, make_client, run_query, to_naive_datetime_index

from .config import LOCATION, PROJECT_ID, WRITE_DISPOSITION

logger = logging.getLogger(__name__)


def save_parquet(df_fe, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df_fe.to_parquet(path)
    logger.info("Saved: %s %s", path, df_fe.shape)


def get_client():
    return make_client(PROJECT_ID, LOCATION)


def save_station_features(client, df_fe, table_id):
    # Nama stasiun (mis. "Bendung Katulampa") dipakai apa adanya sebagai nama
    # kolom, sama seperti tabel station_features yang dibaca preprocessing.
    job_config = bigquery.LoadJobConfig(write_disposition=WRITE_DISPOSITION, autodetect=True)
    job = client.load_table_from_dataframe(df_fe.reset_index(), table_id, job_config=job_config)
    job.result()  # tunggu selesai
    log_table_size(client, table_id)


def load_existing_features(client, table_id):
    """Baca seluruh tabel station_features dari BigQuery (index datetime).
    Return None kalau tabel belum ada atau masih kosong."""
    try:
        df = run_query(client, "common/select_all_ordered", table=table_id)
    except NotFound:
        return None
    if df.empty:
        return None
    return to_naive_datetime_index(df)
