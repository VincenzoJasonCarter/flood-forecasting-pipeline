#!/bin/sh
# Entrypoint Cloud Run Job `flood-hourly` (dipicu Cloud Scheduler tiap jam):
# TMA -> station_features_hourly, curah hujan -> rainfall_hourly, lalu
# (kalau RUN_PREDICT=true) forecast. Keduanya mode incremental.
#
# Langkah berikutnya tetap jalan walau langkah sebelumnya gagal (sumber datanya
# independen), tapi exit code akhir non-zero supaya eksekusi tercatat gagal.
status=0

cd /app/src
python -m raw_preprocessing --incremental --write-bq || status=1
python -m rainfall --incremental --write-bq || status=1

if [ "${RUN_PREDICT:-false}" = "true" ]; then
    cd /app
    python main.py --write-bq || status=1
fi

exit $status
