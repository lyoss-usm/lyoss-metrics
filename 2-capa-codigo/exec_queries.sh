#!/usr/bin/env bash
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

source $SCRIPT_DIR/.env

if [ -z "${GH_TOKEN}" ]; then
    echo "GH_TOKEN tiene que estar definida"
    exit 1
fi

# ------------------------------------------------------ #
API_VERSION=2026-03-10
API_BASE_URL=https://api.github.com

REST() {
    URL_PATH=$1
    curl -L \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer $GH_TOKEN" \
      -H "X-GitHub-Api-Version: $API_VERSION" \
      $API_BASE_URL$URL_PATH
}

GraphQL() {
    QUERY_FILE="$SCRIPT_DIR$1"
    if [ ! -f "$QUERY_FILE" ]; then
        echo "El archivo $QUERY_FILE no existe."
        return 1
    fi

    PAYLOAD=$(jq -n --rawfile q "$QUERY_FILE" '{query: $q}')

    curl -s -L \
      -H "Authorization: Bearer $GH_TOKEN" \
      -H "Content-Type: application/json" \
      -X POST \
      -d "$PAYLOAD" \
      "$API_BASE_URL/graphql"
}

echo "============================================="
echo "Issues y PRs"
echo "============================================="
GraphQL /queries/issues_prs.graphql | jq .
echo -e "\n\n"
echo "============================================="
echo "Commits"
echo "============================================="
GraphQL /queries/commits.graphql | jq .
echo "============================================="
echo "Actions"
echo "============================================="
REST "/repos/lyoss-usm/Plataforma-CdRS/actions/runs" | jq '.workflow_runs[0] | {id, repo_id: .repository.id, name, status, conclusion, created_at, updated_at}'
echo "============================================="
echo "Users"
echo "============================================="
REST "/orgs/lyoss-usm/members" | jq '.[0] | {id, login, type}'
echo "============================================="
echo "Traffico"
echo "============================================="
REST "/repos/lyoss-usm/Plataforma-CdRS/traffic/views" | jq '{views: .views[0]}'
REST "/repos/lyoss-usm/Plataforma-CdRS/traffic/clones" | jq '{clones: .clones[0]}'
REST "/repos/lyoss-usm/Plataforma-CdRS/traffic/popular/referrers" | jq '{referrers: .}'
REST "/repos/lyoss-usm/Plataforma-CdRS/traffic/popular/paths" | jq '{paths: .}'
