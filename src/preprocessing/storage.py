"""Assembling and writing the preprocessing outputs to BigQuery."""

import json
import pickle

import pandas as pd
from google.cloud import bigquery

from .bigquery_io import load_df
from .config import CALENDAR_COLS
from .scaling import make_bq_frame


def save_preprocessed_data(client, df_train, df_val, df_test, column_map, table_id):
    preprocessed_df = pd.concat([
        make_bq_frame(df_train, "train", column_map),
        make_bq_frame(df_val, "val", column_map),
        make_bq_frame(df_test, "test", column_map),
    ], ignore_index=True)
    load_df(client, preprocessed_df, table_id)  # schema autodetect (kolom stasiun dinamis)


def save_metadata(client, station_cols, column_map, saved_at, table_id):
    metadata = {
        "CALENDAR_COLS": CALENDAR_COLS,
        "station_cols": station_cols,
        "feature_cols": station_cols + CALENDAR_COLS,
        "column_map": column_map,  # station -> kolom BigQuery
    }
    schema = [
        bigquery.SchemaField("payload", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("saved_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    metadata_df = pd.DataFrame([{
        "payload": json.dumps(metadata),
        "saved_at": saved_at,
    }])
    load_df(client, metadata_df, table_id, schema)


def save_scalers(client, scalers, saved_at, table_id):
    schema = [
        bigquery.SchemaField("station", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("scaler_blob", "BYTES", mode="REQUIRED"),
        bigquery.SchemaField("saved_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    scalers_df = pd.DataFrame([{
        "station": station,
        "scaler_blob": pickle.dumps(scaler),
        "saved_at": saved_at,
    } for station, scaler in scalers.items()])
    load_df(client, scalers_df, table_id, schema)
