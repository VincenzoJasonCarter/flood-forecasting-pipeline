"""Preprocessing pipeline: BigQuery `station_features` -> train/val/test.

Menyiapkan data mentah dari BigQuery menjadi df_train / df_val / df_test
yang sudah diisi NaN (hourly median) dan di-scale (MinMaxScaler per stasiun).
Hasilnya ditulis kembali ke BigQuery (dataset `tables`) supaya bisa dipakai
ulang oleh notebook model manapun (01_Prophet, 02_LSTM, 03_GRU, 04_TFT)
tanpa mengulang query + preprocessing di tiap notebook, dan tanpa
bergantung pada Google Drive / disk lokal sama sekali.

Tabel yang ditulis:

- preprocessed_data      - df_train/val/test digabung dengan kolom `split`.
- preprocessing_metadata - satu baris JSON berisi daftar kolom kalender,
  stasiun, fitur, dan mapping nama stasiun -> nama kolom BigQuery.
- preprocessing_scalers  - satu baris per stasiun, MinMaxScaler yang
  di-pickle sebagai BYTES.

Jalankan modul ini SEKALI dulu (`python -m preprocessing`) sebelum
menjalankan notebook model.
"""

from .pipeline import run

__all__ = ["run"]
