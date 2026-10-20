"""Orquestador (main.run): flujo, aislamiento, terminate y renovacion de token. Sin red."""
import logging

import pytest

from collector import main
from collector.github_auth import AuthError
from collector.github_client import GitHubClient
from collector.main import Runtime, TokenManager
from conftest import API, FakeWriter

REPOS = ({"id": 1, "full_name": "o/a"}, {"id": 2, "full_name": "o/b"})
PER_REPO = ["actions", "traffic_views", "traffic_clones", "traffic_referrers", "traffic_paths"]
TRAFFIC_URL = {"traffic_views": "traffic/views", "traffic_clones": "traffic/clones",
               "traffic_referrers": "traffic/popular/referrers", "traffic_paths": "traffic/popular/paths"}


def happy(rsps, repos=REPOS, overrides=None):
    """Registra una organizacion sana. overrides: {url: kwargs de rsps.get} reemplaza una ruta."""
    overrides = overrides or {}

    def route(url, **kw):
        rsps.get(url, **overrides.get(url, kw))

    route(f"{API}/orgs/o/repos", json=list(repos))
    route(f"{API}/orgs/o/members", json=[{"id": 1, "login": "u", "type": "User"}])
    route(f"{API}/search/repositories", json={"incomplete_results": False, "items": [{"id": 9}]})
    for r in repos:
        base = f"{API}/repos/{r['full_name']}"
        route(f"{base}/actions/runs", json={"workflow_runs": [{"id": r["id"] * 10}]})
        route(f"{base}/traffic/views", json={"views": [{"timestamp": "2026-10-01T00:00:00Z", "count": 1, "uniques": 1}]})
        route(f"{base}/traffic/clones", json={"clones": []})
        route(f"{base}/traffic/popular/referrers", json=[])
        route(f"{base}/traffic/popular/paths", json=[])


class Clock:
    def __init__(self, step=0.0):
        self.now, self.step = 0.0, step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


def make_runtime(writer=None, get_token=None, clock=None):
    tokens = []

    def default_get_token():
        tokens.append(f"tok-{len(tokens) + 1}")
        return tokens[-1]

    rt = Runtime(org="o", writer=writer or FakeWriter(), get_token=get_token or default_get_token,
                 make_client=GitHubClient, clock=clock or Clock())
    return rt, tokens


def run_full(ctx, writer=None, **kw):
    rt, tokens = make_runtime(writer, **kw)
    return main.run(runtime=rt, ctx=ctx), rt.writer, tokens


def ext_tasks(writer):
    return [r["task"] for r in writer.extraction_rows]


# --- flujo --------------------------------------------------------------------------------------
def test_corrida_completa_ok_y_terminate_es_la_ultima_escritura(ctx, rsps):
    happy(rsps)
    code, w, _ = run_full(ctx)
    assert code == 0
    last = w.calls[-1]
    assert last.table == "extractions" and not last.raised
    assert last.rows == [{
        "extraction_id": ctx.extraction_id, "run_at": ctx.run_at_iso, "task": "terminate", "endpoint": "",
        "page_number": 0, "has_more": False, "cursor": None, "code": 0, "message": None, "result": "succeeded"}]
    assert ext_tasks(w).count("terminate") == 1


def test_orden_de_tareas_y_secuencialidad_por_repo(ctx, rsps):
    happy(rsps)
    _, w, _ = run_full(ctx)
    esperado = (["repos", "users", "trending_repos:stars:100"]
                + [f"{t}:{r['id']}" for r in REPOS for t in PER_REPO] + ["terminate"])
    assert ext_tasks(w) == esperado
    # toda la corrida comparte un unico extraction_id
    assert {r["extraction_id"] for r in w.extraction_rows} == {ctx.extraction_id}


def test_la_lista_de_repos_sale_de_la_tarea_repos_no_de_bigquery(ctx, rsps):
    happy(rsps)
    _, w, _ = run_full(ctx)
    assert not hasattr(w, "query")  # el writer falso no tiene lectura: solo hay escrituras
    assert {c.rows[0]["repo_id"] for c in w.data_calls if c.table == "actions"} == {10 // 10, 20 // 10}


def test_repos_incompleta_corre_users_y_trending_pero_nada_por_repo(ctx, rsps, caplog):
    happy(rsps, overrides={f"{API}/orgs/o/repos": dict(json={"message": "x"}, status=500)})
    with caplog.at_level(logging.INFO):
        code, w, _ = run_full(ctx)
    assert code == 1
    assert ext_tasks(w) == ["repos", "users", "trending_repos:stars:100"]
    assert "terminate" not in ext_tasks(w)
    assert {c.table for c in w.calls} == {"extractions", "users", "trending_repos"}
    assert not any("/repos/o/" in c.request.url for c in rsps.calls)  # ni una llamada por repo


def test_fallo_de_token_inicial_no_escribe_nada(ctx, rsps, caplog):
    def boom():
        raise AuthError("sin acceso al secreto")

    with caplog.at_level(logging.ERROR):
        code, w, _ = run_full(ctx, get_token=boom)
    assert code == 1 and w.calls == [] and len(rsps.calls) == 0
    assert any("sin acceso al secreto" in r.message for r in caplog.records)


def test_fallo_de_carga_de_terminate_da_salida_distinta_de_0(ctx, rsps):
    happy(rsps)
    w = FakeWriter(fail_when=lambda t, rows: t == "extractions" and rows[0]["task"] == "terminate")
    code, w, _ = run_full(ctx, writer=w)
    assert code == 1
    assert w.calls[-1].rows[0]["task"] == "terminate" and w.calls[-1].raised
    assert "terminate" not in ext_tasks(w)


def test_fallas_de_tareas_por_repo_no_cambian_la_salida(ctx, rsps):
    forbidden = dict(json={"message": "Must have push access"}, status=403)
    overrides = {f"{API}/repos/{r['full_name']}/{TRAFFIC_URL[t]}": forbidden
                 for r in REPOS for t in TRAFFIC_URL}
    happy(rsps, overrides=overrides)
    code, w, _ = run_full(ctx)
    assert code == 0 and ext_tasks(w)[-1] == "terminate"
    fallidas = [r for r in w.extraction_rows if r["result"] == "failed"]
    assert len(fallidas) == 8 and {r["code"] for r in fallidas} == {403}


def test_fallas_de_users_y_trending_no_cambian_la_salida(ctx, rsps):
    bad = dict(json={"message": "x"}, status=500)
    happy(rsps, overrides={f"{API}/orgs/o/members": bad, f"{API}/search/repositories": bad})
    code, w, _ = run_full(ctx)
    assert code == 0 and ext_tasks(w)[-1] == "terminate"


def test_repos_vacia_pero_completa_escribe_terminate(ctx, rsps):
    happy(rsps, repos=())
    code, w, _ = run_full(ctx)
    assert code == 0 and ext_tasks(w) == ["repos", "users", "trending_repos:stars:100", "terminate"]


# --- aislamiento --------------------------------------------------------------------------------
def test_excepcion_inesperada_no_detiene_las_siguientes_tareas(ctx, rsps, caplog):
    happy(rsps, overrides={f"{API}/orgs/o/members": dict(body=ValueError("explota"))})
    with caplog.at_level(logging.INFO):
        code, w, _ = run_full(ctx)
    tasks = ext_tasks(w)
    assert "users" not in tasks  # users no pudo registrar nada
    assert "trending_repos:stars:100" in tasks and "actions:1" in tasks and tasks[-1] == "terminate"
    assert code == 0
    trazas = [r for r in caplog.records if r.exc_info and "users" in r.message]
    assert trazas and "ValueError" in repr(trazas[0].exc_info[1].__class__)
    assert any("incompleta users" in r.message and "ValueError" in r.message for r in caplog.records)


def test_excepcion_en_una_tarea_por_repo_continua_con_el_resto(ctx, rsps):
    happy(rsps, overrides={f"{API}/repos/o/a/traffic/views": dict(body=RuntimeError("boom"))})
    code, w, _ = run_full(ctx)
    tasks = ext_tasks(w)
    assert "traffic_views:1" not in tasks
    assert {"traffic_clones:1", "actions:2", "traffic_paths:2", "terminate"} <= set(tasks)
    assert code == 0


def test_excepcion_inesperada_en_repos_cuenta_como_incompleta(ctx, rsps):
    happy(rsps, overrides={f"{API}/orgs/o/repos": dict(body=RuntimeError("boom"))})
    code, w, _ = run_full(ctx)
    assert code == 1 and "terminate" not in ext_tasks(w)
    assert ext_tasks(w) == ["users", "trending_repos:stars:100"]


def test_resumen_por_familia_en_logs(ctx, rsps, caplog):
    forbidden = dict(json={"message": "nope"}, status=403)
    happy(rsps, overrides={f"{API}/repos/o/a/traffic/popular/paths": forbidden})
    with caplog.at_level(logging.INFO):
        run_full(ctx)
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "familia repos: 1 completas, 0 incompletas" in texto
    assert "familia traffic_paths: 1 completas, 1 incompletas" in texto
    assert "familia actions: 2 completas, 0 incompletas" in texto
    assert "incompleta traffic_paths:1: HTTP 403" in texto and "nope" in texto


# --- renovacion de token ------------------------------------------------------------------------
def test_token_se_renueva_pasados_50_minutos_con_reloj_simulado(ctx, rsps):
    happy(rsps)
    # 14 consultas al cliente (1 inicial + 13 tareas), 10 min entre cada una:
    # t=0 token 1; t=3600 renueva (token 2); t=7200 renueva (token 3).
    code, w, tokens = run_full(ctx, clock=Clock(step=600))
    assert code == 0 and tokens == ["tok-1", "tok-2", "tok-3"]
    auth = [c.request.headers["Authorization"] for c in rsps.calls]
    assert auth[0] == "Bearer tok-1" and auth[-1] == "Bearer tok-3"
    assert "Bearer tok-2" in auth


def test_sin_paso_de_tiempo_el_token_se_obtiene_una_vez(ctx, rsps):
    happy(rsps)
    _, _, tokens = run_full(ctx)
    assert tokens == ["tok-1"]


@pytest.mark.parametrize("elapsed,renews", [(3000, False), (3001, True)])
def test_umbral_exacto_de_50_minutos(elapsed, renews):
    clock = Clock()
    rt, tokens = make_runtime(clock=clock)
    manager = TokenManager(rt)
    manager.client()
    clock.now = elapsed
    manager.client()
    assert (len(tokens) == 2) is renews


def test_fallo_de_renovacion_conserva_el_cliente_anterior_y_reintenta():
    clock, calls = Clock(), []

    def get_token():
        calls.append(1)
        if len(calls) == 2:
            raise AuthError("renovacion fallida")
        return f"tok-{len(calls)}"

    rt, _ = make_runtime(get_token=get_token, clock=clock)
    manager = TokenManager(rt)
    first = manager.client()
    clock.now = 4000
    with pytest.raises(AuthError):
        manager.client()
    assert manager._client is first  # sigue el cliente anterior
    assert manager.client() is not first and len(calls) == 3  # el siguiente intento renueva


def test_fallo_de_renovacion_a_mitad_de_corrida_deja_incompleta_solo_esa_tarea(ctx, rsps):
    happy(rsps)
    calls = []

    def get_token():
        calls.append(1)
        if len(calls) == 2:  # primera renovacion
            raise AuthError("renovacion fallida")
        return f"tok-{len(calls)}"

    code, w, _ = run_full(ctx, get_token=get_token, clock=Clock(step=3600))
    # t=0 inicial; t=3600 renueva y falla (tarea repos incompleta); t=7200 renueva con exito
    assert "repos" not in ext_tasks(w) and "users" in ext_tasks(w)
    assert code == 1 and "terminate" not in ext_tasks(w)  # repos no se completo


# --- uso y configuracion ------------------------------------------------------------------------
def test_tarea_desconocida_o_repo_id_mal_usado(ctx):
    rt, _ = make_runtime()
    assert main.run("nada", runtime=rt, ctx=ctx) == 2
    assert main.run("users", repo_id=3, runtime=rt, ctx=ctx) == 2
    assert rt.writer.calls == []


def test_sin_variables_de_entorno_sale_con_2():
    assert main.run() == 2


def test_modo_tarea_suelta_no_escribe_terminate(ctx, rsps):
    happy(rsps)
    rt, _ = make_runtime()
    code = main.run("users", runtime=rt, ctx=ctx)
    assert code == 0 and ext_tasks(rt.writer) == ["users"]


def test_modo_tarea_suelta_por_repo(ctx, rsps):
    happy(rsps)
    rsps.get(f"{API}/repositories/2", json={"id": 2, "full_name": "o/b"})
    rt, _ = make_runtime()
    code = main.run("traffic_views", repo_id=2, runtime=rt, ctx=ctx)
    assert code == 0 and ext_tasks(rt.writer) == ["traffic_views:2"]
