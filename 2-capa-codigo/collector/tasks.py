"""Ejecucion de tareas con el invariante de escritura por pagina (mvp-ingesta.md, seccion 4).

Una fila de `extractions` con result=succeeded para la pagina k solo se escribe despues de que
los datos de la pagina k quedaron cargados.
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Iterable, Optional

from .bq_writer import BigQueryWriter
from .context import RunContext
from .github_client import GitHubClient, Page
from .mapping import (action_row, extraction_row, repo_row, traffic_clone_row,
                      traffic_path_row, traffic_referrer_row, traffic_view_row, trending_row,
                      user_row)

log = logging.getLogger(__name__)

TRENDING_DAYS = 7
TRENDING_ATTRIBUTE = "stars"
TRENDING_TOP_LIMIT = 100
SEARCH_MAX_PER_PAGE = 100

# (rows crudas de la pagina, ctx, task, page_number) -> filas raw
PageMapper = Callable[[list[Any], RunContext, str, int], list[dict[str, Any]]]


@dataclass(frozen=True)
class RepoRef:
    """Lo que las tareas por repo necesitan de la tarea `repos` (en memoria, nunca de BigQuery)."""
    id: int
    full_name: str


@dataclass
class TaskResult:
    task: str
    complete: bool = False
    pages: int = 0               # paginas recibidas de la API
    data_rows: int = 0           # filas cargadas en la tabla de datos
    extraction_rows: int = 0     # filas cargadas en extractions
    error: Optional[str] = None  # motivo de la ultima falla, si hubo
    repos: list[RepoRef] = field(default_factory=list)  # solo la tarea `repos`


def execute_task(
    ctx: RunContext,
    writer: BigQueryWriter,
    task: str,
    endpoint: str,
    table: str,
    pages: Iterable[Page],
    to_rows: PageMapper,
) -> TaskResult:
    result = TaskResult(task=task)
    last_page: Optional[Page] = None
    try:
        for page_number, page in enumerate(pages, start=1):
            result.pages = page_number
            last_page = page

            # a) pagina fallida: se registra en extractions y termina la tarea
            if page.result == "failed":
                result.error = f"HTTP {page.code}: {page.message}"
                log.error("[%s] pagina %d fallo: code=%s message=%s",
                          task, page_number, page.code, page.message)
                try:
                    writer.load_extraction_row(extraction_row(ctx, task, endpoint, page_number, page))
                    result.extraction_rows += 1
                except Exception as e:  # noqa: BLE001
                    log.error("[%s] no se pudo registrar la pagina fallida %d: %s: %s",
                              task, page_number, type(e).__name__, e)
                return result

            # b) 0 filas: no hay carga de datos. c) con filas: carga; si falla, sin fila de extractions
            if page.rows:
                try:
                    rows = to_rows(page.rows, ctx, task, page_number)
                    writer.load_rows(table, rows)
                    result.data_rows += len(rows)
                except Exception as e:  # noqa: BLE001
                    result.error = f"carga de datos fallo: {type(e).__name__}: {e}"
                    log.error("[%s] pagina %d: %s (sin fila de extractions)",
                              task, page_number, result.error)
                    return result

            # d) datos cargados (o sin datos): se registra la pagina como succeeded
            try:
                writer.load_extraction_row(extraction_row(ctx, task, endpoint, page_number, page))
                result.extraction_rows += 1
            except Exception as e:  # noqa: BLE001
                result.error = f"carga de extractions fallo: {type(e).__name__}: {e}"
                log.error("[%s] pagina %d: %s", task, page_number, result.error)
                return result

            log.info("[%s] pagina %d ok: %d filas, has_more=%s",
                     task, page_number, len(page.rows), page.has_more)

            # e) has_more: siguiente pagina; si no, la tarea quedo completa
            if not page.has_more:
                result.complete = True
        return result
    finally:
        if last_page is not None and last_page.rate_remaining is not None:
            log.info("[%s] rate limit restante (%s): %d",
                     task, last_page.rate_resource, last_page.rate_remaining)


# --- Tareas ---------------------------------------------------------------------------------
def run_repos(ctx: RunContext, client: GitHubClient, writer: BigQueryWriter, org: str) -> TaskResult:
    endpoint = f"/orgs/{org}/repos"
    refs: list[RepoRef] = []

    def to_rows(raw: list[Any], c: RunContext, task: str, n: int) -> list[dict[str, Any]]:
        rows = [repo_row(r, c, task, n) for r in raw]
        refs.extend(RepoRef(r["id"], r["full_name"]) for r in raw)
        return rows

    result = execute_task(ctx, writer, "repos", endpoint, "repos",
                          client.rest_pages(endpoint, {"type": "all"}), to_rows)
    result.repos = refs if result.complete else []  # incompleta: no se ejecutan tareas por repo
    return result


def run_users(ctx: RunContext, client: GitHubClient, writer: BigQueryWriter, org: str) -> TaskResult:
    endpoint = f"/orgs/{org}/members"
    return execute_task(
        ctx, writer, "users", endpoint, "users", client.rest_pages(endpoint),
        lambda raw, c, t, n: [user_row(r, c, t, n) for r in raw])


def run_trending_repos(ctx: RunContext, client: GitHubClient, writer: BigQueryWriter,
                       attribute: str = TRENDING_ATTRIBUTE,
                       top_limit: int = TRENDING_TOP_LIMIT) -> TaskResult:
    task = f"trending_repos:{attribute}:{top_limit}"
    if top_limit > SEARCH_MAX_PER_PAGE:
        # La tarea es de una sola pagina (<= 100): falla antes de llamar a la API, sin filas.
        msg = f"top_limit={top_limit} > {SEARCH_MAX_PER_PAGE}: la tarea es de una sola pagina"
        log.error("[%s] %s", task, msg)
        return TaskResult(task=task, error=msg)

    endpoint = "/search/repositories"
    since = (ctx.run_at - timedelta(days=TRENDING_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {"q": f"created:>={since}", "sort": attribute, "order": "desc", "per_page": top_limit}

    def to_rows(raw: list[Any], c: RunContext, t: str, n: int) -> list[dict[str, Any]]:
        # top_ord: unico campo calculado (posicion en el top, desde 1)
        return [trending_row(r, c, t, n, attribute, top_limit, i)
                for i, r in enumerate(raw[:top_limit], start=1)]

    return execute_task(
        ctx, writer, task, endpoint, "trending_repos",
        client.rest_pages(endpoint, params, key="items", single_page=True), to_rows)


def run_actions(ctx: RunContext, client: GitHubClient, writer: BigQueryWriter,
                repo: RepoRef) -> TaskResult:
    endpoint = f"/repos/{repo.full_name}/actions/runs"
    return execute_task(
        ctx, writer, f"actions:{repo.id}", endpoint, "actions",
        client.rest_pages(endpoint, key="workflow_runs"),
        lambda raw, c, t, n: [action_row(r, c, t, n, repo.id) for r in raw])


# nombre de tarea -> (sufijo del endpoint, clave del contenedor, tabla, mapper)
_TRAFFIC = {
    "traffic_views": ("/traffic/views", "views", traffic_view_row),
    "traffic_clones": ("/traffic/clones", "clones", traffic_clone_row),
    "traffic_referrers": ("/traffic/popular/referrers", None, traffic_referrer_row),
    "traffic_paths": ("/traffic/popular/paths", None, traffic_path_row),
}


def run_traffic(ctx: RunContext, client: GitHubClient, writer: BigQueryWriter,
                repo: RepoRef, table: str) -> TaskResult:
    """traffic_views | traffic_clones | traffic_referrers | traffic_paths: una sola pagina."""
    suffix, key, mapper = _TRAFFIC[table]
    endpoint = f"/repos/{repo.full_name}{suffix}"
    return execute_task(
        ctx, writer, f"{table}:{repo.id}", endpoint, table,
        client.rest_pages(endpoint, key=key, single_page=True),
        lambda raw, c, t, n: [mapper(r, c, t, n, repo.id) for r in raw])


PER_REPO_TASKS = ("actions", *_TRAFFIC)
