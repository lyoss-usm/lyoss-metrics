"""Ejecucion de tareas con el invariante de escritura por pagina (mvp-ingesta.md, seccion 4).

Una fila de `extractions` con result=succeeded para la pagina k solo se escribe despues de que
los datos de la pagina k quedaron cargados.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from .bq_writer import BigQueryWriter
from .context import RunContext
from .github_client import GitHubClient, Page
from .mapping import extraction_row, repo_row

log = logging.getLogger(__name__)


@dataclass
class TaskResult:
    task: str
    complete: bool = False
    pages: int = 0               # paginas recibidas de la API
    data_rows: int = 0           # filas cargadas en la tabla de datos
    extraction_rows: int = 0     # filas cargadas en extractions
    error: Optional[str] = None  # motivo de la ultima falla, si hubo


def execute_task(
    ctx: RunContext,
    writer: BigQueryWriter,
    task: str,
    endpoint: str,
    table: str,
    pages: Iterable[Page],
    to_row: Callable[[dict[str, Any], RunContext, str, int], dict[str, Any]],
) -> TaskResult:
    result = TaskResult(task=task)
    for page_number, page in enumerate(pages, start=1):
        result.pages = page_number

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
                rows = [to_row(r, ctx, task, page_number) for r in page.rows]
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


def run_repos(ctx: RunContext, client: GitHubClient, writer: BigQueryWriter, org: str) -> TaskResult:
    endpoint = f"/orgs/{org}/repos"
    return execute_task(ctx, writer, "repos", endpoint, "repos",
                        client.rest_pages(endpoint, {"type": "all"}), repo_row)
