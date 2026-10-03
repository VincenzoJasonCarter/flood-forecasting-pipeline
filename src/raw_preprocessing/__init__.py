"""Raw preprocessing: API sisteminformasibanjir -> `station_features_{hourly,daily}`.

Versi modul dari notebook EDA_Preprocess_Flood (bagian non-EDA), dengan
langkah tambahan agregasi harian (opsional, lihat `granularity` di config):

1. crawl laporan pos pengamatan harian dari API,
2. flatten + dedup, resample per jam (mean) per stasiun,
3. tandai outlier (IQR, z-score, ambang fisik) — spike cleaning opsional,
4. pivot ke wide (satu kolom per stasiun) di grid per jam kontinu,
5. isi gap pendek (interpolasi waktu -> ffill -> bfill, limit GAP_LIMIT jam),
6. granularity daily: agregasi ke max harian (puncak muka air per hari);
   granularity hourly: grid per jam dipakai apa adanya,
7. tambah fitur kalender (CALENDAR_COLS).

Formatnya sama dengan `station_features` (input package `preprocessing`
dan `prediction`), tapi ditulis ke tabel terpisah per granularity
(`station_features_hourly` / `station_features_daily`) supaya tabel yang
dipakai model saat ini tidak tertimpa. Output selalu
ditulis ke parquet lokal; tabel BigQuery hanya ditulis kalau diminta
eksplisit (`--write-bq`).

Token API dibaca dari env var (lihat `api.token_env` di
config/raw_preprocessing.yaml).
"""

from .pipeline import run

__all__ = ["run"]
