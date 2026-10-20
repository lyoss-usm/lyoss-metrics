#!/usr/bin/env bash
# Programa la ejecucion diaria del Cloud Run Job (mvp-ingesta.md, secciones 8 y 9):
#   1. sa-scheduler recibe roles/run.invoker SOLO sobre el job (incluye run.jobs.run).
#   2. Cloud Scheduler (00:30 UTC) hace POST a la API v2 de Cloud Run con OAuth (no OIDC).
# Reejecutable: el binding de IAM es idempotente y el job de Scheduler se crea o se actualiza.
#
# Uso: PROJECT_ID=mi-proyecto ./infra/05_scheduler.sh
# Obligatoria: PROJECT_ID
# Opcionales:  REGION (us-central1), JOB_NAME (lyoss-collector), SCHEDULER_NAME (<JOB_NAME>-diario),
#              SA_SCHEDULER (sa-scheduler), CRON ("30 0 * * *")
set -euo pipefail

: "${PROJECT_ID:?Define PROJECT_ID}"
REGION="${REGION:-us-central1}"
JOB_NAME="${JOB_NAME:-lyoss-collector}"
SCHEDULER_NAME="${SCHEDULER_NAME:-${JOB_NAME}-diario}"
SA_SCHEDULER="${SA_SCHEDULER:-sa-scheduler}"
CRON="${CRON:-30 0 * * *}"
TIME_ZONE="Etc/UTC"

SA_EMAIL="${SA_SCHEDULER}@${PROJECT_ID}.iam.gserviceaccount.com"
URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run"

gcloud services enable cloudscheduler.googleapis.com --project="$PROJECT_ID"

# Prerrequisitos: la cuenta y el job deben existir.
gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null \
  || { echo "ERROR: no existe $SA_EMAIL" >&2; exit 1; }
gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" >/dev/null \
  || { echo "ERROR: no existe el Cloud Run Job $JOB_NAME en $REGION" >&2; exit 1; }

# 1. IAM a nivel de job (no de proyecto). roles/run.invoker incluye run.jobs.run,
#    asi que no hace falta un rol custom.
gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
  --region="$REGION" --project="$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" >/dev/null
echo "OK: ${SA_EMAIL} es run.invoker sobre el job ${JOB_NAME}"

# 2. Job de Cloud Scheduler: HTTP POST + OAuth (la API de Cloud Run exige access token, no OIDC)
if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  ACTION=update
else
  ACTION=create
fi
echo ">> gcloud scheduler jobs $ACTION http $SCHEDULER_NAME"

gcloud scheduler jobs "$ACTION" http "$SCHEDULER_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="$CRON" \
  --time-zone="$TIME_ZONE" \
  --uri="$URI" \
  --http-method=POST \
  --message-body='{}' \
  --oauth-service-account-email="$SA_EMAIL" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --max-retry-attempts=0

echo
echo "Verificar: gcloud scheduler jobs describe $SCHEDULER_NAME --location=$REGION --project=$PROJECT_ID"
echo "Forzar:    gcloud scheduler jobs run $SCHEDULER_NAME --location=$REGION --project=$PROJECT_ID"
