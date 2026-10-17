#!/usr/bin/env python3
"""Audita los endpoints de GitHub usados por la ingesta.

1. Valida que los campos esperados existan en las respuestas y reporta sus tipos.
2. Estima (o mide con --full) el costo en cuota de API de una corrida completa.

Uso:
    python api_audit.py          # estima paginas a partir de la 1a pagina + metadatos
    python api_audit.py --full   # pagina TODO literalmente (mas caro en cuota)

El token se lee de GH_TOKEN (entorno) o, si no existe, de .env junto a este script.
"""
import argparse
import math
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
API = "https://api.github.com"
API_VERSION = "2026-03-10"
ORG = "lyoss-usm"
REPO = "Plataforma-CdRS"
PER_PAGE = 100
SEARCH_MAX_RESULTS = 1000  # tope duro de /search

# --- Modelo esperado: rutas con punto; "author.login" navega objetos anidados ---------
REPO_FIELDS = [
    "id", "name", "full_name", "visibility", "description", "fork", "archived", "disabled",
    "is_template", "stargazers_count", "forks_count", "open_issues_count", "size",
    "created_at", "updated_at", "pushed_at", "has_issues", "has_projects", "has_wiki",
    "has_pages", "has_discussions", "allow_forking", "language", "topics", "default_branch",
    "license.key",
]
ORG_REPO_FIELDS = REPO_FIELDS + [
    "custom_properties.active", "custom_properties.help", "custom_properties.display",
]
TRAFFIC_FIELDS = ["timestamp", "count", "uniques"]

TYPE_NAMES = {str: "string", int: "integer", float: "number", bool: "boolean",
              list: "array", dict: "object", type(None): "null"}
MISSING = object()


def load_token():
    token = os.environ.get("GH_TOKEN")
    if token:
        return token
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?GH_TOKEN\s*=\s*(.*)", line)
            if m:
                return m.group(1).strip().strip("'\"")
    sys.exit("No se encontro GH_TOKEN (entorno o .env).")


class Client:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        })
        self.calls = 0

    def get(self, url, **params):
        self.calls += 1
        return self.s.get(url if url.startswith("http") else API + url,
                          params=params or None, timeout=30)

    def graphql(self, query, variables=None):
        self.calls += 1
        r = self.s.post(f"{API}/graphql", json={"query": query, "variables": variables or {}},
                        timeout=60)
        r.raise_for_status()
        body = r.json()
        if "errors" in body and not body.get("data"):
            raise RuntimeError(body["errors"][0].get("message", "graphql error"))
        return body


# --- Introspeccion de campos -----------------------------------------------------------
def resolve(item, path):
    cur = item
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None if cur is None else MISSING
        if part not in cur:
            return MISSING
        cur = cur[part]
    return cur


def inspect_fields(items, paths):
    """-> ({path: 'string|null'}, [paths ausentes en todos los items])"""
    found, missing = {}, []
    for p in paths:
        types = set()
        for it in items:
            v = resolve(it, p)
            if v is not MISSING:
                types.add(TYPE_NAMES.get(type(v), type(v).__name__))
        if types:
            found[p] = "|".join(sorted(types))
        else:
            missing.append(p)
    return found, missing


def wrap(entries, indent="    ", width=100):
    lines, cur = [], indent
    for e in entries:
        if len(cur) + len(e) + 2 > width and cur.strip():
            lines.append(cur.rstrip())
            cur = indent
        cur += e + "  "
    if cur.strip():
        lines.append(cur.rstrip())
    return "\n".join(lines)


reports = []  # (titulo, n_items, found, missing, error)


def report_fields(title, items, paths, error=None):
    if error:
        reports.append((title, 0, {}, [], error))
        return
    found, missing = inspect_fields(items, paths)
    if not items:
        missing = []  # sin datos no se puede afirmar nada
        reports.append((title, 0, {}, [], "sin items en la respuesta (no verificable)"))
        return
    reports.append((title, len(items), found, missing, None))


# --- Costos ------------------------------------------------------------------------------
costs = []  # dict(name, pool, unit, requests, note)


def add_cost(name, pool, unit, requests_n, note, total=None):
    costs.append({"name": name, "pool": pool, "unit": unit, "reqs": requests_n, "note": note,
                  "total": unit * requests_n if total is None else total})


def link_last_page(resp):
    last = resp.links.get("last")
    if not last:
        return None, 1
    m = re.search(r"[?&]page=(\d+)", last["url"])
    return last["url"], int(m.group(1)) if m else 1


def error_of(resp):
    try:
        msg = resp.json().get("message", "")
    except ValueError:
        msg = resp.text[:80]
    return f"HTTP {resp.status_code}: {msg}"


# --- REST paginado -----------------------------------------------------------------------
def rest_list(cl, path, key, full, **params):
    """Devuelve (items_1a_pagina_o_todas, n_paginas, n_items_total, error)."""
    r = cl.get(path, per_page=PER_PAGE, **params)
    if not r.ok:
        return [], 0, 0, error_of(r)
    body = r.json()
    items = body[key] if key else body
    total_count = body.get("total_count") if key else None
    last_url, pages = link_last_page(r)

    if full:
        pages_done = 1
        while "next" in r.links and not (key and pages_done * PER_PAGE >= SEARCH_MAX_RESULTS):
            r = cl.get(r.links["next"]["url"])
            if not r.ok:
                break
            items += (r.json()[key] if key else r.json())
            pages_done += 1
        return items, pages_done, len(items), None

    if key:  # search: total_count conocido, tope 1000 resultados
        n_total = min(total_count or len(items), SEARCH_MAX_RESULTS)
        return items, max(1, math.ceil(n_total / PER_PAGE)), n_total, None
    if last_url:  # 1 request extra para contar items exactos en la ultima pagina
        last = cl.get(last_url)
        n_last = len(last.json()) if last.ok else 0
        return items, pages, (pages - 1) * PER_PAGE + n_last, None
    return items, 1, len(items), None


# --- GraphQL (queries embebidas, paginadas con cursores y @include) -----------------------
RATE = "rateLimit { cost limit remaining resetAt }"
PAGE = "totalCount pageInfo { hasNextPage endCursor }"

Q_ISSUES_PRS = f"""
query($owner: String!, $name: String!, $ic: String, $pc: String, $doI: Boolean!, $doP: Boolean!) {{
  {RATE}
  repository(owner: $owner, name: $name) {{
    issues(first: {PER_PAGE}, after: $ic) @include(if: $doI) {{
      {PAGE}
      nodes {{ id: databaseId number author {{ login }} state
               created_at: createdAt closed_at: closedAt }}
    }}
    pullRequests(first: {PER_PAGE}, after: $pc) @include(if: $doP) {{
      {PAGE}
      nodes {{ id: databaseId number author {{ login }} state
               created_at: createdAt merged_at: mergedAt closed_at: closedAt }}
    }}
  }}
}}"""

Q_COMMITS = f"""
query($owner: String!, $name: String!, $cc: String, $doC: Boolean!) {{
  {RATE}
  repository(owner: $owner, name: $name) {{
    defaultBranchRef {{ target {{ ... on Commit {{
      history(first: {PER_PAGE}, after: $cc) @include(if: $doC) {{
        {PAGE}
        nodes {{ sha: oid author {{ user {{ login }} date }} }}
      }}
    }} }} }}
  }}
}}"""

Q_OVERVIEW = f"""
query($owner: String!, $after: String) {{
  {RATE}
  organization(login: $owner) {{
    repositories(first: {PER_PAGE}, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{
        name isArchived
        issues {{ totalCount }}
        pullRequests {{ totalCount }}
        defaultBranchRef {{ target {{ ... on Commit {{ history {{ totalCount }} }} }} }}
      }}
    }}
  }}
}}"""

# tipo -> (query, {conexion: (var_cursor, var_flag)})
GQL_KINDS = {
    "issues_prs": (Q_ISSUES_PRS, {"issues": ("ic", "doI"), "pullRequests": ("pc", "doP")}),
    "commits": (Q_COMMITS, {"history": ("cc", "doC")}),
}


def gql_connections(repo_data):
    out = {k: v for k, v in (repo_data or {}).items() if isinstance(v, dict) and "nodes" in v}
    target = ((repo_data or {}).get("defaultBranchRef") or {}).get("target") or {}
    if target.get("history"):
        out["history"] = target["history"]
    return out


def fetch_repo(cl, kind, name, max_pages=None):
    """Pagina un repo. -> ({conexion: [nodes]}, n_requests, costo_total, costo_unitario_1a_pag)"""
    query, conns = GQL_KINDS[kind]
    items = {c: [] for c in conns}
    active = {c: True for c in conns}
    cursors = {c: None for c in conns}
    reqs = cost = unit = 0
    while any(active.values()) and (max_pages is None or reqs < max_pages):
        variables = {"owner": ORG, "name": name}
        for c, (vc, vf) in conns.items():
            variables[vc], variables[vf] = cursors[c], active[c]
        body = cl.graphql(query, variables)
        reqs += 1
        cost += body["data"]["rateLimit"]["cost"]
        unit = unit or body["data"]["rateLimit"]["cost"]
        state = gql_connections((body["data"] or {}).get("repository"))
        for c in conns:
            if not active[c]:
                continue
            s = state.get(c)
            if not s:
                active[c] = False
                continue
            items[c] += s["nodes"]
            active[c] = s["pageInfo"]["hasNextPage"]
            cursors[c] = s["pageInfo"]["endCursor"]
    return items, reqs, cost, unit


def gql_overview(cl):
    """Conteos por repo (issues, PRs, commits) en pocas requests."""
    repos, after = [], None
    while True:
        body = cl.graphql(Q_OVERVIEW, {"owner": ORG, "after": after})
        conn = body["data"]["organization"]["repositories"]
        for n in conn["nodes"]:
            hist = (((n.get("defaultBranchRef") or {}).get("target") or {}).get("history") or {})
            repos.append({"name": n["name"], "issues": n["issues"]["totalCount"],
                          "prs": n["pullRequests"]["totalCount"],
                          "commits": hist.get("totalCount", 0)})
        if not conn["pageInfo"]["hasNextPage"]:
            return repos
        after = conn["pageInfo"]["endCursor"]


def pages_for(n):
    return max(1, math.ceil(n / PER_PAGE))


def audit_graphql(cl, full):
    try:
        repos = gql_overview(cl)
    except Exception as e:  # noqa: BLE001
        for t in ("Issues (GraphQL)", "Pull Requests (GraphQL)", "Commits (GraphQL)"):
            report_fields(t, [], [], error=str(e))
        return 0
    sample = max(repos, key=lambda r: r["issues"] + r["prs"] + r["commits"],
                 default={"name": REPO})["name"]

    specs = {
        "issues_prs": [("Issues (GraphQL)", "issues",
                        ["id", "number", "author.login", "state", "created_at", "closed_at"]),
                       ("Pull Requests (GraphQL)", "pullRequests",
                        ["id", "number", "author.login", "state", "created_at", "merged_at",
                         "closed_at"])],
        "commits": [("Commits (GraphQL)", "history",
                     ["sha", "author.user.login", "author.date"])],
    }
    labels = {"issues_prs": "GraphQL issues+PRs", "commits": "GraphQL commits"}
    for kind in GQL_KINDS:
        items = {c: [] for c in GQL_KINDS[kind][1]}
        reqs = cost = unit = 0
        try:
            if full:
                for r in repos:
                    it, q, c_, u = fetch_repo(cl, kind, r["name"])
                    for k in items:
                        items[k] += it[k]
                    reqs, cost, unit = reqs + q, cost + c_, unit or u
            else:
                items, _, _, unit = fetch_repo(cl, kind, sample, max_pages=1)
                for r in repos:
                    reqs += (max(pages_for(r["issues"]), pages_for(r["prs"]))
                             if kind == "issues_prs" else pages_for(r["commits"]))
                cost = reqs * unit
        except Exception as e:  # noqa: BLE001
            for title, _, _ in specs[kind]:
                report_fields(title, [], [], error=str(e))
            continue
        for title, conn, paths in specs[kind]:
            report_fields(title, items[conn], paths)
        add_cost(f"{labels[kind]} (x{len(repos)} repos)", "graphql", unit, reqs,
                 f"{sum(r['issues'] for r in repos)} issues, {sum(r['prs'] for r in repos)} PRs, "
                 f"{sum(r['commits'] for r in repos)} commits" if kind == "issues_prs"
                 else f"{sum(r['commits'] for r in repos)} commits", total=cost)
    return len(repos)


# --- Main ----------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="paginar todo literalmente en vez de estimar")
    full = ap.parse_args().full
    cl = Client(load_token())
    mode = "medido" if full else "estimado"

    # 1-2. GraphQL (todos los repos de la org)
    n_gql_repos = audit_graphql(cl, full)

    # 3. Repos de la org
    repos, pages, n_repos, err = rest_list(cl, f"/orgs/{ORG}/repos", None, full)
    report_fields("Repos de la org (REST)", repos, ORG_REPO_FIELDS, err)
    add_cost("REST /orgs/{org}/repos", "core", 1, pages, f"{n_repos} repos")

    # 4. Trending (search)
    since = (date.today() - timedelta(days=30)).isoformat()
    trending, pages, n_tr, err = rest_list(
        cl, "/search/repositories", "items", full,
        q=f"created:>{since}", sort="stars", order="desc")
    report_fields("Trending repos (REST search)", trending, REPO_FIELDS, err)
    add_cost("REST /search/repositories", "search", 1, pages,
             f"{n_tr} resultados (tope {SEARCH_MAX_RESULTS})")

    # 5. Trafico: 4 endpoints por repo
    base = f"/repos/{ORG}/{REPO}/traffic"
    traffic = [
        ("Traffic views", f"{base}/views", "views", TRAFFIC_FIELDS),
        ("Traffic clones", f"{base}/clones", "clones", TRAFFIC_FIELDS),
        ("Traffic referrers", f"{base}/popular/referrers", None,
         ["referrer", "count", "uniques"]),
        ("Traffic paths", f"{base}/popular/paths", None,
         ["path", "title", "count", "uniques"]),
    ]
    for title, path, key, paths in traffic:
        r = cl.get(path)
        if not r.ok:
            report_fields(f"{title} (REST)", [], paths, error_of(r))
        else:
            body = r.json()
            report_fields(f"{title} (REST)", body[key] if key else body, paths)
    add_cost("REST traffic (x4 endpoints)", "core", 1, 4 * max(n_repos, 1),
             f"4 req x {n_repos} repos")

    # --- Reporte ---------------------------------------------------------------------------
    print()
    for title, n, found, missing, err in reports:
        print(f"## {title}" + (f"  [{n} items]" if n else ""))
        if err:
            print(f"    ! {err}")
            continue
        print(wrap([f"{p}:{t}" for p, t in found.items()]))
        if missing:
            print(f"    x NO EXISTEN: {', '.join(missing)}")
    print()

    header = ["Peticion", "Pool", "Costo/req", "Reqs/run", "Costo total", "Detalle"]
    rows = [[c["name"], c["pool"], str(c["unit"]), str(c["reqs"]),
             str(c["total"]), c["note"]] for c in costs]
    widths = [max(len(r[i]) for r in rows + [header]) for i in range(len(header))]

    def fmt(r):
        return "  ".join(v.ljust(w) for v, w in zip(r, widths))

    print(f"Costo de una corrida completa ({mode})")
    print(fmt(header))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(fmt(r))
    print()
    limits = {"core": "5000/h", "graphql": "5000 pts/h", "search": "30/min"}
    for pool in ("core", "graphql", "search"):
        total = sum(c["total"] for c in costs if c["pool"] == pool)
        print(f"  Total {pool:<8}: {total:>5}   (limite {limits[pool]})")
    print(f"\n  Supuestos: GraphQL recorre los {n_gql_repos} repos de la org; trafico = 4 req"
          f" x {n_repos} repos.")


if __name__ == "__main__":
    main()
