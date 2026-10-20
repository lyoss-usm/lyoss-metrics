#!/usr/bin/env bash
# Crea el dataset `raw_test` (pruebas locales) con las mismas 12 tablas que `raw`.
# Reutiliza sql/ddl/*.sql sustituyendo el nombre del dataset, para no duplicar esquemas.
# A diferencia de `raw`, las tablas expiran solas (7 dias) para no acumular basura de pruebas.
# Uso: PROJECT_ID=mi-proyecto ./infra/02_create_raw_test.sh   (idempotente)
#      RESET=1 PROJECT_ID=... ./infra/02_create_raw_test.sh   (borra y recrea el dataset)
set -euo pipefail

: "${PROJECT_ID:?Define PROJECT_ID}"
LOCATION="us-central1"
DATASET="raw_test"
EXPIRATION_SECONDS=$((7 * 24 * 3600))
DDL_DIR="$(cd "$(dirname "$0")/../sql/ddl" && pwd)"

if [[ "${RESET:-0}" == "1" ]]; then
  bq --project_id="$PROJECT_ID" rm -r -f -d "$PROJECT_ID:$DATASET" || true
fi

if ! bq --project_id="$PROJECT_ID" show --dataset "$PROJECT_ID:$DATASET" >/dev/null 2>&1; then
  bq --project_id="$PROJECT_ID" --location="$LOCATION" mk --dataset \
    --default_table_expiration "$EXPIRATION_SECONDS" \
    --description "Pruebas locales del recolector (expira a 7 dias)" \
    "$PROJECT_ID:$DATASET"
fi

for f in extractions repos trending_repos users actions commits \
         pull_requests issues traffic_views traffic_clones \
         traffic_referrers traffic_paths; do
  echo ">> $DATASET.$f"
  sed "s/\`raw\./\`$DATASET./" "$DDL_DIR/$f.sql" \
    | bq --project_id="$PROJECT_ID" --location="$LOCATION" query \
        --use_legacy_sql=false --nouse_cache
done

bq --project_id="$PROJECT_ID" ls --max_results=50 "$PROJECT_ID:$DATASET"
