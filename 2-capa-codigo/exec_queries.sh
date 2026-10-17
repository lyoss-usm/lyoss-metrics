#!/usr/bin/env bash
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

source "$SCRIPT_DIR/.env"

if [ -z "${GH_TOKEN}" ]; then
    echo "GH_TOKEN tiene que estar definida"
    exit 1
fi

# ------------------------------------------------------ #
API_VERSION="2026-03-10"
API_BASE_URL="https://api.github.com"
HEADER_TMP="/tmp/gh_headers.txt"

REST() {
    URL_PATH=$1
    curl -s -L -D "$HEADER_TMP" \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer $GH_TOKEN" \
      -H "X-GitHub-Api-Version: $API_VERSION" \
      "$API_BASE_URL$URL_PATH"
}

GraphQL() {
    QUERY_FILE="$SCRIPT_DIR$1"
    if [ ! -f "$QUERY_FILE" ]; then
        echo "El archivo $QUERY_FILE no existe." >&2
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

PRINT_REST_COST() {
    REMAINING=$(grep -i "x-ratelimit-remaining" "$HEADER_TMP" | awk '{print $2}' | tr -d '\r')
    echo -e "\n  Costo REST: 1 llamada | Peticiones restantes: $REMAINING\n"
}

PRINT_GQL_COST() {
    JSON_PAYLOAD=$1
    echo "$JSON_PAYLOAD" | jq -r '"\n  Costo GraphQL: \(.data.rateLimit.cost) puntos | Puntos restantes: \(.data.rateLimit.remaining)\n"'
}

CHECK_FIELDS() {
    JSON_PAYLOAD=$1
    JQ_FILTER=$2
    echo "$JSON_PAYLOAD" | jq -r "$JQ_FILTER | to_entries[] | \"   [\(.value | type)] \(.key)\""
}

# ------------------------------------------------------ #

echo "============================================="
echo " 1. Issues y PRs (GraphQL)"
echo "============================================="
RESP_GQL=$(GraphQL "/queries/issues_prs.graphql")
echo "Campos mapeados para Issues:"
CHECK_FIELDS "$RESP_GQL" '.data.repository.issues.nodes[0] | {id, number, user_login: .author.login, state, created_at: .createdAt, closed_at: .closedAt}'
echo "---"
echo "Campos mapeados para Pull Requests:"
CHECK_FIELDS "$RESP_GQL" '.data.repository.pullRequests.nodes[0] | {id, number, user_login: .author.login, state, created_at: .createdAt, merged_at: .mergedAt, closed_at: .closedAt}'
PRINT_GQL_COST "$RESP_GQL"


echo "============================================="
echo " 2. Commits (GraphQL)"
echo "============================================="
RESP_GQL=$(GraphQL "/queries/commits.graphql")
echo "Campos mapeados para Commits:"
CHECK_FIELDS "$RESP_GQL" '.data.repository.defaultBranchRef.target.history.nodes[0] | {sha: .oid, user_login: .author.user.login, commit_date: .author.date}'
PRINT_GQL_COST "$RESP_GQL"


echo "============================================="
echo " 3. Actions (REST)"
echo "============================================="
RESP_REST=$(REST "/repos/lyoss-usm/Plataforma-CdRS/actions/runs")
echo "Campos mapeados para Actions:"
CHECK_FIELDS "$RESP_REST" '.workflow_runs[0] | {id, repo_id: .repository.id, name, status, conclusion, created_at, updated_at}'
PRINT_REST_COST


echo "============================================="
echo " 4. Users (REST)"
echo "============================================="
RESP_REST=$(REST "/orgs/lyoss-usm/members")
echo "Campos mapeados para Users:"
CHECK_FIELDS "$RESP_REST" '.[0] | {id, login, type}'
PRINT_REST_COST


echo "============================================="
echo " 5. Tráfico: Views (REST)"
echo "============================================="
RESP_REST=$(REST "/repos/lyoss-usm/Plataforma-CdRS/traffic/views")
echo "Campos mapeados para Traffic Views:"
CHECK_FIELDS "$RESP_REST" '.views[0] | {timestamp, count, uniques}'
PRINT_REST_COST


echo "============================================="
echo " 6. Repos (REST)"
echo "============================================="
RESP_REST=$(REST "/orgs/lyoss-usm/repos?per_page=100")
echo "Campos mapeados para Repos:"
CHECK_FIELDS "$RESP_REST" '.[0] | {
  id, name, full_name, visibility, description, fork, archived, disabled, is_template,
  stargazers_count, forks_count, open_issues_count, size, created_at, updated_at, pushed_at,
  has_issues, has_projects, has_wiki, has_pages, has_discussions, allow_forking, language,
  default_branch, license_key: .license?.key, custom_active: .custom_properties?.active,
  custom_help: .custom_properties?.help, custom_display: .custom_properties?.display
}'
PRINT_REST_COST
