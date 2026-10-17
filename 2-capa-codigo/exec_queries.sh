#!/usr/bin/env bash
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

source "$SCRIPT_DIR/.env"

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
    PAYLOAD=$(jq -n --rawfile q "$QUERY_FILE" '{query: $q}')
    curl -s -L \
      -H "Authorization: Bearer $GH_TOKEN" \
      -H "Content-Type: application/json" \
      -X POST \
      -d "$PAYLOAD" \
      "$API_BASE_URL/graphql"
}

PRINT_REST_COST() {
    REMAINING=$(grep -i -E "^x-ratelimit-remaining:" "$HEADER_TMP" | awk '{print $2}' | tr -d $'\r')
    echo -e "\n  REST Remaining: $REMAINING\n"
}

PRINT_GQL_COST() {
    echo "$1" | jq -r '"\n  GraphQL Costo: \(.data.rateLimit.cost) | Remaining: \(.data.rateLimit.remaining)\n"'
}

CHECK_TYPES() {
    JSON_ARRAY=$1
    JQ_FILTER=$2
    echo "$JSON_ARRAY" | jq -r "
      $JQ_FILTER |
      map(to_entries) | flatten | group_by(.key) |
      map(\"   [\(map(.value | type) | unique | join(\", \"))] \(.[0].key)\") | .[]
    "
}

echo "============================================="
echo " 1. Issues y PRs (GraphQL - Muestra Completa)"
echo "============================================="
RESP_GQL=$(GraphQL "/queries/issues_prs.graphql")
echo "Tipos detectados en Issues:"
CHECK_TYPES "$RESP_GQL" '.data.repository.issues.nodes | map({id, number, user_login: .author.login, state, created_at, closed_at})'
echo "---"
echo "Tipos detectados en Pull Requests:"
CHECK_TYPES "$RESP_GQL" '.data.repository.pullRequests.nodes | map({id, number, user_login: .author.login, state, created_at, merged_at, closed_at})'
PRINT_GQL_COST "$RESP_GQL"

echo "============================================="
echo " 2. Commits (GraphQL - Muestra Completa)"
echo "============================================="
RESP_GQL=$(GraphQL "/queries/commits.graphql")
echo "Tipos detectados en Commits:"
CHECK_TYPES "$RESP_GQL" '.data.repository.defaultBranchRef.target.history.nodes | map({sha, user_login: .author.user.login, commit_date: .author.date})'
PRINT_GQL_COST "$RESP_GQL"

echo "============================================="
echo " 3. Repos (REST)"
echo "============================================="
RESP_REST=$(REST "/orgs/lyoss-usm/repos?per_page=100")
CHECK_TYPES "$RESP_REST" 'map({
  id, name, full_name, visibility, description, fork, archived, disabled, is_template,
  stargazers_count, forks_count, open_issues_count, size, created_at, updated_at, pushed_at,
  has_issues, has_projects, has_wiki, has_pages, has_discussions, allow_forking, language, topics,
  default_branch, license_key: .license?.key, custom_active: .custom_properties?.active,
  custom_help: .custom_properties?.help, custom_display: .custom_properties?.display
})'
PRINT_REST_COST

echo "============================================="
echo " 4. Tráfico Total (REST)"
echo "============================================="
RESP_VIEWS=$(REST "/repos/lyoss-usm/Plataforma-CdRS/traffic/views")
echo "Tipos en Views:" && CHECK_TYPES "$RESP_VIEWS" '.views | map({timestamp, count, uniques})'

RESP_CLONES=$(REST "/repos/lyoss-usm/Plataforma-CdRS/traffic/clones")
echo "Tipos en Clones:" && CHECK_TYPES "$RESP_CLONES" '.clones | map({timestamp, count, uniques})'

RESP_REFS=$(REST "/repos/lyoss-usm/Plataforma-CdRS/traffic/popular/referrers")
echo "Tipos en Referrers:" && CHECK_TYPES "$RESP_REFS" 'map({referrer, count, uniques})'

RESP_PATHS=$(REST "/repos/lyoss-usm/Plataforma-CdRS/traffic/popular/paths")
echo "Tipos en Paths:" && CHECK_TYPES "$RESP_PATHS" 'map({path, title, count, uniques})'
