#!/usr/bin/env bash
# Crea el dataset `raw` (us-central1, sin expiracion por defecto) y las 12 tablas raw.
# Uso: PROJECT_ID=mi-proyecto ./infra/01_create_raw.sh   (idempotente)
set -euo pipefail

: "${PROJECT_ID:?Define PROJECT_ID}"
LOCATION="us-central1"
DDL_DIR="$(cd "$(dirname "$0")/../sql/ddl" && pwd)"

# 1. Dataset sin default_table_expiration ni default_partition_expiration.
if ! bq --project_id="$PROJECT_ID" show --dataset "$PROJECT_ID:raw" >/dev/null 2>&1; then
  bq --project_id="$PROJECT_ID" --location="$LOCATION" mk --dataset \
    --description "Capa raw: datos crudos de GitHub (append-only)" \
    "$PROJECT_ID:raw"
fi

# 2. Verificar que no hereda expiraciones (proyectos que fueron sandbox: 60 dias).
bq --project_id="$PROJECT_ID" update \
  --default_table_expiration 0 \
  --default_partition_expiration 0 \
  "$PROJECT_ID:raw"

# 3. DDL de las 12 tablas.
for f in extractions repos trending_repos users actions commits \
         pull_requests issues traffic_views traffic_clones \
         traffic_referrers traffic_paths; do
  echo ">> $f"
  bq --project_id="$PROJECT_ID" --location="$LOCATION" query \
    --use_legacy_sql=false --nouse_cache < "$DDL_DIR/$f.sql"
done

# 4. Verificacion: expiraciones vacias y 12 tablas.
bq --project_id="$PROJECT_ID" show --format=prettyjson "$PROJECT_ID:raw" \
  | grep -E 'defaultTableExpirationMs|defaultPartitionExpirationMs' \
  || echo "OK: dataset sin expiraciones por defecto"
bq --project_id="$PROJECT_ID" ls --max_results=50 "$PROJECT_ID:raw"
