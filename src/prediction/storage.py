"""Persist forecast pipeline output back to BigQuery."""

from google.cloud import bigquery

from .config import FORECAST_TABLE


def save_forecast(client, forecast_df):
    schema = [
        bigquery.SchemaField("model", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("station", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("horizon", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("as_of", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("forecast_time", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("predicted_value_cm", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("generated_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    job_config = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_APPEND")
    job = client.load_table_from_dataframe(forecast_df, FORECAST_TABLE, job_config=job_config)
    job.result()
    tbl = client.get_table(FORECAST_TABLE)
    print(f"  {FORECAST_TABLE}: {tbl.num_rows:,} rows total")
