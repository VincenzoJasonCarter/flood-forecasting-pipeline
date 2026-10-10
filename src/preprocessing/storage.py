"""Assembling and writing the preprocessing outputs to BigQuery."""

import json
import pickle

import pandas as pd
from google.cloud import bigquery

from .bigquery_io import load_df
from .scaling import make_bq_frame


def save_preprocessed_data(client, df_train, df_val, df_test, column_map, table_id):
    preprocessed_df = pd.concat([
        make_bq_frame(df_train, "train", column_map),
        make_bq_frame(df_val, "val", column_map),
        make_bq_frame(df_test, "test", column_map),
    ], ignore_index=True)
    load_df(client, preprocessed_df, table_id)  # schema autodetect (kolom stasiun dinamis)


def save_metadata(client, metadata, saved_at, table_id):
    """Simpan payload `metadata.build_metadata` sebagai satu baris JSON."""
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
    """Satu baris per scaler. Kolom `station` berisi nama stasiun, atau nama
    kolom fitur hujan (rain_*) untuk scaler fitur hujan."""
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
