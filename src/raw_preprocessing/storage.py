"""Writing the station features to a local parquet file and/or BigQuery."""

from google.cloud import bigquery

from .config import LOCATION, PROJECT_ID, WRITE_DISPOSITION


def save_parquet(df_fe, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df_fe.to_parquet(path)
    print(f"Saved: {path} {df_fe.shape}")


def get_client():
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)


def save_station_features(client, df_fe, table_id):
    # Nama stasiun (mis. "Bendung Katulampa") dipakai apa adanya sebagai nama
    # kolom, sama seperti tabel station_features yang dibaca preprocessing.
    job_config = bigquery.LoadJobConfig(write_disposition=WRITE_DISPOSITION, autodetect=True)
    job = client.load_table_from_dataframe(df_fe.reset_index(), table_id, job_config=job_config)
    job.result()  # tunggu selesai
    tbl = client.get_table(table_id)
    print(f"  {table_id}: {tbl.num_rows:,} rows")
