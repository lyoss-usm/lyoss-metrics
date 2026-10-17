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
