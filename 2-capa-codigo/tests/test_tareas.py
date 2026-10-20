"""C) Definiciones de tareas (tasks.py) sobre HTTP simulado y un writer falso."""
import logging
from urllib.parse import parse_qs, urlparse

from collector import tasks
from collector.tasks import RepoRef
from conftest import API, FakeWriter

REPO = RepoRef(7, "o/r")


def query_of(call) -> dict:
    return parse_qs(urlparse(call.request.url).query)


# --- trending_repos -----------------------------------------------------------------------------
def test_trending_top_limit_mayor_a_100_no_llama_a_nada(ctx, client, rsps, caplog):
    w = FakeWriter()
    with caplog.at_level(logging.ERROR):
        result = tasks.run_trending_repos(ctx, client, w, top_limit=101)
    assert len(rsps.calls) == 0 and w.calls == []
    assert not result.complete and result.task == "trending_repos:stars:101"
    assert "top_limit=101" in result.error
    assert any("top_limit=101" in r.message for r in caplog.records)


def test_trending_parametros_de_la_consulta(ctx, client, rsps):
    rsps.get(f"{API}/search/repositories", json={"incomplete_results": False, "items": [{"id": 1}]})
    tasks.run_trending_repos(ctx, client, FakeWriter())
    q = query_of(rsps.calls[0])
    # run_at = 2026-10-20T01:02:03.456789Z  ->  menos 7 dias, UTC, a segundos
    assert q["q"] == ["created:>=2026-10-13T01:02:03Z"]
    assert q["sort"] == ["stars"] and q["order"] == ["desc"] and q["per_page"] == ["100"]


def test_trending_top_ord_y_una_sola_pagina(ctx, client, rsps):
    items = [{"id": i, "license": None} for i in range(1, 4)]
    rsps.get(f"{API}/search/repositories", json={"incomplete_results": False, "items": items},
             headers={"Link": f'<{API}/search/repositories?page=2>; rel="next"'})
    w = FakeWriter()
    result = tasks.run_trending_repos(ctx, client, w)
    rows = w.data_calls[0].rows
    assert result.task == "trending_repos:stars:100" and result.complete and result.pages == 1
    assert [r["top_ord"] for r in rows] == [1, 2, 3]
    assert {(r["attribute"], r["top_limit"], r["page_number"], r["task"]) for r in rows} == {
        ("stars", 100, 1, "trending_repos:stars:100")}
    ext = w.extraction_rows[0]
    assert (ext["page_number"], ext["has_more"], ext["cursor"]) == (1, False, None)
    assert len(rsps.calls) == 1  # aunque el Link anuncie mas, no se pide la pagina 2


def test_trending_trunca_a_top_limit(ctx, client, rsps):
    items = [{"id": i} for i in range(1, 6)]
    rsps.get(f"{API}/search/repositories", json={"incomplete_results": False, "items": items})
    w = FakeWriter()
    result = tasks.run_trending_repos(ctx, client, w, top_limit=3)
    assert [r["top_ord"] for r in w.data_calls[0].rows] == [1, 2, 3]
    assert query_of(rsps.calls[0])["per_page"] == ["3"] and result.task == "trending_repos:stars:3"


def test_trending_incomplete_results_no_carga_datos(ctx, client, rsps):
    rsps.get(f"{API}/search/repositories", json={"incomplete_results": True, "items": [{"id": 1}]})
    w = FakeWriter()
    result = tasks.run_trending_repos(ctx, client, w)
    assert not result.complete and w.data_calls == []
    (ext,) = w.extraction_rows
    assert (ext["result"], ext["code"], ext["message"]) == ("failed", 200, "incomplete_results=true")


# --- repos --------------------------------------------------------------------------------------
def test_repos_completa_devuelve_la_lista_en_memoria(ctx, client, rsps):
    p2 = f"{API}/orgs/o/repos-pagina-2"
    rsps.get(f"{API}/orgs/o/repos", json=[{"id": 1, "full_name": "o/a"}],
             headers={"Link": f'<{p2}>; rel="next"'})
    rsps.get(p2, json=[{"id": 2, "full_name": "o/b"}])
    result = tasks.run_repos(ctx, client, FakeWriter(), "o")
    assert result.complete and result.repos == [RepoRef(1, "o/a"), RepoRef(2, "o/b")]


def test_repos_incompleta_deja_la_lista_vacia(ctx, client, rsps):
    p2 = f"{API}/orgs/o/repos-pagina-2"
    rsps.get(f"{API}/orgs/o/repos", json=[{"id": 1, "full_name": "o/a"}],
             headers={"Link": f'<{p2}>; rel="next"'})
    rsps.get(p2, json={"message": "x"}, status=500)
    result = tasks.run_repos(ctx, client, FakeWriter(), "o")
    assert not result.complete and result.repos == []


def test_repos_con_carga_fallida_deja_la_lista_vacia(ctx, client, rsps):
    rsps.get(f"{API}/orgs/o/repos", json=[{"id": 1, "full_name": "o/a"}])
    result = tasks.run_repos(ctx, client, FakeWriter(fail_on_table="repos"), "o")
    assert not result.complete and result.repos == []


# --- actions y users ----------------------------------------------------------------------------
def test_actions_usa_el_repo_id_de_la_lista(ctx, client, rsps):
    p2 = f"{API}/repos/o/r/actions/runs-pagina-2"
    run = {"id": 1, "repository": {"id": 999}, "conclusion": None}
    rsps.get(f"{API}/repos/o/r/actions/runs", json={"total_count": 2, "workflow_runs": [run]},
             headers={"Link": f'<{p2}>; rel="next"'})
    rsps.get(p2, json={"total_count": 2, "workflow_runs": [{**run, "id": 2}]})
    w = FakeWriter()
    result = tasks.run_actions(ctx, client, w, REPO)
    assert result.task == "actions:7" and result.complete and result.pages == 2
    assert {r["repo_id"] for c in w.data_calls for r in c.rows} == {7}


def test_users_pagina_la_membresia(ctx, client, rsps):
    rsps.get(f"{API}/orgs/o/members", json=[{"id": 1, "login": "a", "type": "User"}])
    w = FakeWriter()
    result = tasks.run_users(ctx, client, w, "o")
    assert result.task == "users" and result.complete
    assert w.data_calls[0].rows[0]["login"] == "a"


# --- trafico ------------------------------------------------------------------------------------
def test_trafico_views_una_fila_por_dia(ctx, client, rsps):
    days = [{"timestamp": "2026-10-01T00:00:00Z", "count": 3, "uniques": 1},
            {"timestamp": "2026-10-02T00:00:00Z", "count": 5, "uniques": 2}]
    rsps.get(f"{API}/repos/o/r/traffic/views", json={"count": 8, "uniques": 3, "views": days})
    w = FakeWriter()
    result = tasks.run_traffic(ctx, client, w, REPO, "traffic_views")
    assert result.task == "traffic_views:7" and result.complete and result.data_rows == 2
    assert [r["timestamp"] for r in w.data_calls[0].rows] == [d["timestamp"] for d in days]
    assert {r["repo_id"] for r in w.data_calls[0].rows} == {7}


def test_trafico_lista_vacia_es_succeeded_con_una_fila_de_extractions(ctx, client, rsps):
    for table, path, body in (("traffic_views", "traffic/views", {"count": 0, "uniques": 0, "views": []}),
                              ("traffic_clones", "traffic/clones", {"count": 0, "uniques": 0, "clones": []}),
                              ("traffic_referrers", "traffic/popular/referrers", []),
                              ("traffic_paths", "traffic/popular/paths", [])):
        rsps.reset()
        rsps.get(f"{API}/repos/o/r/{path}", json=body)
        w = FakeWriter()
        result = tasks.run_traffic(ctx, client, w, REPO, table)
        assert result.complete and result.data_rows == 0, table
        assert [c.table for c in w.calls] == ["extractions"], table
        (ext,) = w.extraction_rows
        assert (ext["task"], ext["page_number"], ext["has_more"], ext["cursor"], ext["code"]) == (
            f"{table}:7", 1, False, None, 200)
        assert ext["endpoint"] == f"/repos/o/r/{path}"


def test_trafico_referrers_y_paths_sin_paginacion(ctx, client, rsps):
    link = {"Link": f'<{API}/otra>; rel="next"'}
    rsps.get(f"{API}/repos/o/r/traffic/popular/referrers", json=[{"referrer": "x.com", "count": 1, "uniques": 1}],
             headers=link)
    w = FakeWriter()
    result = tasks.run_traffic(ctx, client, w, REPO, "traffic_referrers")
    assert result.complete and len(rsps.calls) == 1 and w.data_calls[0].rows[0]["referrer"] == "x.com"


def test_trafico_403_solo_registra_la_fila_failed(ctx, client, rsps):
    rsps.get(f"{API}/repos/o/r/traffic/clones", json={"message": "Must have push access"}, status=403)
    w = FakeWriter()
    result = tasks.run_traffic(ctx, client, w, REPO, "traffic_clones")
    assert not result.complete and w.data_calls == []
    (ext,) = w.extraction_rows
    assert (ext["task"], ext["result"], ext["code"], ext["page_number"]) == ("traffic_clones:7", "failed", 403, 1)
    assert "Must have push access" in ext["message"]


# --- rate limit ---------------------------------------------------------------------------------
def test_loguea_el_rate_limit_restante(ctx, client, rsps, caplog):
    rsps.get(f"{API}/orgs/o/members", json=[], headers={"x-ratelimit-resource": "core",
                                                        "x-ratelimit-remaining": "4990"})
    with caplog.at_level(logging.INFO):
        tasks.run_users(ctx, client, FakeWriter(), "o")
    assert any("rate limit restante (core): 4990" in r.message for r in caplog.records)
