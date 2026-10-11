#!/usr/bin/env bash
# Setup sekali: Cloud Run Job `flood-hourly` + Cloud Scheduler tiap jam di
# asia-southeast2 (Jakarta). Harus di region Indonesia: API sisteminformasibanjir
# memblokir IP luar Indonesia (dari us-central1 / GitHub Actions request-nya timeout).
#
# Prasyarat: `gcloud auth login`, SIBANJIR_TOKEN di .env, backfill awal sudah ada
# di BigQuery. Dijalankan dari root repo:  bash deploy/setup_cloud_run.sh
# Aman dijalankan ulang; untuk deploy ulang image saja, cukup langkah build + job.
set -euo pipefail

PROJECT=thesis-506605
REGION=asia-southeast2
REPO=flood
IMAGE=$REGION-docker.pkg.dev/$PROJECT/$REPO/pipeline:latest
JOB=flood-hourly
SA_NAME=flood-hourly
SA=$SA_NAME@$PROJECT.iam.gserviceaccount.com
SECRET=sibanjir-token
SCHEDULE="15 * * * *"   # menit ke-15 tiap jam, Asia/Jakarta
RUN_PREDICT=false       # true setelah model_selection_hourly + bobot hourly ada

gc() { gcloud --project "$PROJECT" --quiet "$@"; }

echo "== APIs"
gc services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
    cloudscheduler.googleapis.com secretmanager.googleapis.com bigquery.googleapis.com

echo "== Artifact Registry"
gc artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 ||
    gc artifacts repositories create "$REPO" --location "$REGION" --repository-format docker

echo "== Build image (Cloud Build, context dibatasi .gcloudignore)"
gc builds submit --region "$REGION" --tag "$IMAGE" .

echo "== Service account"
gc iam service-accounts describe "$SA" >/dev/null 2>&1 ||
    gc iam service-accounts create "$SA_NAME" --display-name "Flood hourly job"
for role in roles/bigquery.dataEditor roles/bigquery.jobUser roles/run.invoker; do
    gc projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role "$role" \
        --condition None >/dev/null
done

echo "== Secret $SECRET (dari .env)"
TOKEN=$(grep '^SIBANJIR_TOKEN=' .env | cut -d= -f2- | tr -d '"\r')
if gc secrets describe "$SECRET" >/dev/null 2>&1; then
    printf %s "$TOKEN" | gc secrets versions add "$SECRET" --data-file=-
else
    printf %s "$TOKEN" | gc secrets create "$SECRET" --replication-policy automatic --data-file=-
fi
gc secrets add-iam-policy-binding "$SECRET" --member "serviceAccount:$SA" \
    --role roles/secretmanager.secretAccessor >/dev/null

echo "== Cloud Run Job $JOB"
# TZ: date.today() (tanggal akhir crawl) ikut WIB, bukan UTC — kalau UTC, data
# 00:00-07:00 WIB baru ter-crawl setelah jam 07:00.
gc run jobs deploy "$JOB" --region "$REGION" --image "$IMAGE" --service-account "$SA" \
    --command sh --args /app/deploy/hourly_job.sh \
    --set-secrets "SIBANJIR_TOKEN=$SECRET:latest" \
    --set-env-vars "RUN_PREDICT=$RUN_PREDICT,TZ=Asia/Jakarta,PYTHONUNBUFFERED=1" \
    --cpu 1 --memory 2Gi --task-timeout 30m --max-retries 0

echo "== Cloud Scheduler"
URI="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$JOB:run"
if gc scheduler jobs describe "$JOB-trigger" --location "$REGION" >/dev/null 2>&1; then verb=update; else verb=create; fi
gc scheduler jobs "$verb" http "$JOB-trigger" --location "$REGION" \
    --schedule "$SCHEDULE" --time-zone "Asia/Jakarta" \
    --uri "$URI" --http-method POST --oauth-service-account-email "$SA"

echo "Selesai. Jalankan sekali manual:  gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait"
