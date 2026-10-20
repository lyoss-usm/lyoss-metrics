#!/usr/bin/env bash
# Crea o actualiza el Cloud Run Job del recolector (mvp-ingesta.md, secciones 7 y 9).
# Reejecutable: si el job existe lo actualiza (p. ej. al cambiar la imagen), si no lo crea.
#
# Uso: PROJECT_ID=... ORG=... APP_ID=... INSTALL_ID=... SECRETO=... \
#        ./infra/04_cloud_run_job.sh <ETIQUETA_DE_IMAGEN>
#
# Obligatorias: PROJECT_ID, ORG, APP_ID, INSTALL_ID, SECRETO y la etiqueta (argumento 1 o IMAGE_TAG)
# Opcionales:   REGION (us-central1), AR_REPO (lyoss), IMAGE_NAME (collector),
#               JOB_NAME (lyoss-collector), SA_NAME (sa-collector), JOB_DATASET (raw)
# No lee .env: JOB_DATASET es independiente de la variable DATASET de las pruebas locales.
set -euo pipefail

: "${PROJECT_ID:?Define PROJECT_ID}"
: "${ORG:?Define ORG}"
: "${APP_ID:?Define APP_ID}"
: "${INSTALL_ID:?Define INSTALL_ID}"
: "${SECRETO:?Define SECRETO (nombre del secreto con la clave privada de la GH App)}"
IMAGE_TAG="${1:-${IMAGE_TAG:-}}"
: "${IMAGE_TAG:?Indica la etiqueta de la imagen: ./infra/04_cloud_run_job.sh 20261020-0222}"

REGION="${REGION:-us-central1}"
AR_REPO="${AR_REPO:-lyoss}"
IMAGE_NAME="${IMAGE_NAME:-collector}"
JOB_NAME="${JOB_NAME:-lyoss-collector}"
SA_NAME="${SA_NAME:-sa-collector}"
JOB_DATASET="${JOB_DATASET:-raw}"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${IMAGE_NAME}:${IMAGE_TAG}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud services enable run.googleapis.com --project="$PROJECT_ID"

# La cuenta de servicio debe existir (nunca se usa la cuenta por defecto de Compute).
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "ERROR: no existe la cuenta de servicio $SA_EMAIL" >&2
  echo "Creala con: gcloud iam service-accounts create $SA_NAME --project=$PROJECT_ID" >&2
  exit 1
fi

# Delimitador '@' para que los valores puedan contener comas.
ENV_VARS="^@^PROYECTO=${PROJECT_ID}@DATASET=${JOB_DATASET}@SECRETO=${SECRETO}@ORG=${ORG}@APP_ID=${APP_ID}@INSTALL_ID=${INSTALL_ID}"

if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  ACTION=update
else
  ACTION=create
fi
echo ">> gcloud run jobs $ACTION $JOB_NAME  (imagen: $IMAGE)"

gcloud run jobs "$ACTION" "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --image="$IMAGE" \
  --tasks=1 \
  --parallelism=1 \
  --max-retries=0 \
  --task-timeout=3600s \
  --cpu=1 \
  --memory=512Mi \
  --service-account="$SA_EMAIL" \
  --set-env-vars="$ENV_VARS"

echo
echo "Comprobar:  gcloud run jobs describe $JOB_NAME --region=$REGION --project=$PROJECT_ID"
echo "Ejecutar:   gcloud run jobs execute $JOB_NAME --region=$REGION --project=$PROJECT_ID --wait"
