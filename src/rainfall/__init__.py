"""Rainfall: Open-Meteo (ECMWF IFS ~9 km) -> `rainfall_hourly`.

1. temukan sel grid model di kotak hulu (config `grid`): titik uji disebar
   lalu sel yang sama digabung, jadi koordinat tidak perlu presisi,
2. ambil curah hujan per jam semua sel (Historical Forecast API), dipotong
   per rentang waktu x kelompok sel,
3. buang jam yang belum terjadi (API ikut mengembalikan prakiraan),
4. simpan wide frame (satu kolom per sel, `rain_<lat>_<lon>`) ke parquet
   lokal, dan ke BigQuery kalau diminta (`--write-bq`).

Mode incremental mengambil ulang beberapa hari terakhir dan menimpa tabel,
sama seperti `raw_preprocessing`. `rainfall.analysis` me-ranking sel per
stasiun (korelasi silang hujan vs kenaikan TMA) untuk memilih fitur.
"""

from .pipeline import run

__all__ = ["run"]
