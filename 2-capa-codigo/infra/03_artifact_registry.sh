#!/usr/bin/env bash
# Crea el repositorio Docker de Artifact Registry (con politica de limpieza: conserva las
# 2 ultimas versiones) y configura la autenticacion de Docker contra el registro.
# Uso: PROJECT_ID=mi-proyecto ./infra/03_artifact_registry.sh   (idempotente)
# Variables: PROJECT_ID (obligatoria), REGION (us-central1), AR_REPO (lyoss)
set -euo pipefail

: "${PROJECT_ID:?Define PROJECT_ID}"
REGION="${REGION:-us-central1}"
AR_REPO="${AR_REPO:-lyoss}"
KEEP_VERSIONS=2

gcloud services enable artifactregistry.googleapis.com --project="$PROJECT_ID"

# 1. Repositorio Docker (solo si no existe)
if ! gcloud artifacts repositories describe "$AR_REPO" \
      --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --description="Imagenes del recolector de metricas"
fi

# 2. Limpieza: se conservan las N versiones mas recientes y se borra el resto.
#    (En Artifact Registry la politica Keep tiene precedencia sobre Delete.)
POLICY_FILE="$(mktemp)"
trap 'rm -f "$POLICY_FILE"' EXIT
cat > "$POLICY_FILE" <<EOF
[
  {
    "name": "keep-last-${KEEP_VERSIONS}",
    "action": {"type": "Keep"},
    "mostRecentVersions": {"keepCount": ${KEEP_VERSIONS}}
  },
  {
    "name": "delete-the-rest",
    "action": {"type": "Delete"},
    "condition": {"tagState": "any"}
  }
]
EOF
# Sin --dry-run las politicas se aplican (borran) de verdad.
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" \
  --location="$REGION" --project="$PROJECT_ID" --policy="$POLICY_FILE"

# 3. Autenticacion de Docker contra el registro regional
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# 4. Verificacion
gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" --project="$PROJECT_ID" \
  --format="yaml(name,format,cleanupPolicies,cleanupPolicyDryRun)"
echo "Imagen: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/collector:<etiqueta>"
