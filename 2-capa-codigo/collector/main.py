"""Orquestacion de la corrida (mvp-ingesta.md, seccion 4).

Corrida completa:        python -m collector.main
Una sola tarea (pruebas): python -m collector.main --task actions [--repo-id N]
    tareas: repos | users | trending_repos | actions | traffic_views | traffic_clones |
            traffic_referrers | traffic_paths

Las tareas por repo sin --repo-id se ejecutan para todos los repos de la organizacion
(la lista se obtiene de la API y nunca de BigQuery).
"""
import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from dotenv import load_dotenv

from .bq_writer import BigQueryWriter
from .context import RunContext
from .github_auth import AuthError, installation_token, read_pem
from .github_client import GitHubClient
from .mapping import terminate_row
from .tasks import (PER_REPO_TASKS, TRENDING_ATTRIBUTE, TRENDING_TOP_LIMIT, RepoRef, TaskResult,
                    run_actions, run_repos, run_traffic, run_trending_repos, run_users)

log = logging.getLogger("collector")

REQUIRED_ENV = ("PROYECTO", "DATASET", "SECRETO", "ORG", "APP_ID", "INSTALL_ID")
TASKS = ("repos", "users", "trending_repos", *PER_REPO_TASKS)
TOKEN_REFRESH_AFTER = 50 * 60  # el token de instalacion dura 1 h; se renueva pasados 50 min


class ConfigError(Exception):
    pass


def load_config() -> dict[str, str]:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise ConfigError("faltan variables de entorno: " + ", ".join(missing))
    return {k: os.environ[k] for k in REQUIRED_ENV}


@dataclass
class Runtime:
    """Dependencias de la corrida; los tests inyectan dobles."""
    org: str
    writer: Any                                   # interfaz de BigQueryWriter
    get_token: Callable[[], str]                  # lanza AuthError si falla
    make_client: Callable[[str], GitHubClient] = GitHubClient
    clock: Callable[[], float] = time.monotonic   # segundos


def build_runtime(cfg: dict[str, str]) -> Runtime:
    def get_token() -> str:
        pem = read_pem(cfg["PROYECTO"], cfg["SECRETO"])
        try:
            return installation_token(cfg["APP_ID"], cfg["INSTALL_ID"], pem)
        finally:
            pem = None

    return Runtime(org=cfg["ORG"], writer=BigQueryWriter(cfg["PROYECTO"], cfg["DATASET"]),
                   get_token=get_token)


class TokenManager:
    """Entrega un cliente con token vigente; renueva si pasaron mas de `refresh_after` segundos."""

    def __init__(self, rt: Runtime, refresh_after: float = TOKEN_REFRESH_AFTER):
        self._rt, self._refresh_after = rt, refresh_after
        self._client: Optional[GitHubClient] = None
        self._obtained = 0.0

    def client(self) -> GitHubClient:
        now = self._rt.clock()
        if self._client is None or now - self._obtained > self._refresh_after:
            renewal = self._client is not None
            client = self._rt.make_client(self._rt.get_token())  # si falla, se conserva el anterior
            self._client, self._obtained = client, now
            if renewal:
                log.info("token de instalacion renovado")
        return self._client


def family(task: str) -> str:
    return task.split(":", 1)[0]


class Orchestrator:
    def __init__(self, ctx: RunContext, rt: Runtime, tokens: TokenManager):
        self.ctx, self.rt, self.tokens = ctx, rt, tokens
        self.results: list[TaskResult] = []

    def guard(self, name: str, fn: Callable[[GitHubClient], TaskResult]) -> TaskResult:
        """Ejecuta una tarea aislada: cualquier excepcion la deja incompleta y la corrida sigue."""
        try:
            result = fn(self.tokens.client())  # el token se renueva antes de cada tarea
        except Exception as e:  # noqa: BLE001
            log.exception("[%s] excepcion inesperada", name)
            result = TaskResult(task=name, error=f"excepcion inesperada: {type(e).__name__}: {e}")
        self.results.append(result)
        return result

    # --- tareas ---------------------------------------------------------------------------------
    def _repos(self) -> TaskResult:
        return self.guard("repos", lambda c: run_repos(self.ctx, c, self.rt.writer, self.rt.org))

    def _users(self) -> TaskResult:
        return self.guard("users", lambda c: run_users(self.ctx, c, self.rt.writer, self.rt.org))

    def _trending(self) -> TaskResult:
        name = f"trending_repos:{TRENDING_ATTRIBUTE}:{TRENDING_TOP_LIMIT}"
        return self.guard(name, lambda c: run_trending_repos(self.ctx, c, self.rt.writer))

    def _per_repo(self, task: str, repo: RepoRef) -> TaskResult:
        name = f"{task}:{repo.id}"
        if task == "actions":
            return self.guard(name, lambda c: run_actions(self.ctx, c, self.rt.writer, repo))
        return self.guard(name, lambda c: run_traffic(self.ctx, c, self.rt.writer, repo, task))

    def _terminate(self) -> bool:
        try:
            self.rt.writer.load_extraction_row(terminate_row(self.ctx))
        except Exception:  # noqa: BLE001
            log.exception("[terminate] no se pudo escribir la fila de cierre")
            self.results.append(TaskResult(task="terminate", error="carga de terminate fallo"))
            return False
        self.results.append(TaskResult(task="terminate", complete=True, extraction_rows=1))
        return True

    # --- flujos ---------------------------------------------------------------------------------
    def run_full(self) -> int:
        repos = self._repos()
        self._users()      # independientes de repos: se ejecutan siempre
        self._trending()
        exit_code = 0
        if repos.complete:
            for repo in repos.repos:  # lista en memoria, secuencial
                for task in PER_REPO_TASKS:
                    self._per_repo(task, repo)
            if not self._terminate():  # siempre la ultima escritura
                exit_code = 1
        else:
            log.error("repos incompleta: sin tareas por repo y sin terminate")
            exit_code = 1
        self.log_summary()
        return exit_code

    def run_single(self, task: str, repo_id: Optional[int]) -> int:
        if task == "repos":
            self._repos()
        elif task == "users":
            self._users()
        elif task == "trending_repos":
            self._trending()
        else:
            try:
                repos = resolve_repos(self.tokens.client(), self.rt.org, repo_id)
            except Exception:  # noqa: BLE001
                log.exception("no se pudo obtener la lista de repos")
                return 1
            if repos is None:
                return 1
            for repo in repos:
                self._per_repo(task, repo)
        self.log_summary()
        return 0 if all(r.complete for r in self.results) else 1

    def log_summary(self) -> None:
        by_family: dict[str, list[TaskResult]] = defaultdict(list)
        for r in self.results:
            by_family[family(r.task)].append(r)
        log.info("== resumen de la corrida extraction_id=%d ==", self.ctx.extraction_id)
        for fam, items in by_family.items():
            done = sum(1 for r in items if r.complete)
            log.info("familia %s: %d completas, %d incompletas", fam, done, len(items) - done)
        incompletas = [r for r in self.results if not r.complete]
        for r in incompletas:
            log.warning("incompleta %s: %s", r.task, r.error or "sin detalle")
        if not incompletas:
            log.info("todas las tareas completas")


def resolve_repos(client: GitHubClient, org: str, repo_id: Optional[int]) -> Optional[list[RepoRef]]:
    """Repos sobre los que correr una tarea por repo suelta (modo --task). None si falla.

    No carga nada a BigQuery. En la corrida completa la lista sale de la tarea `repos`.
    """
    if repo_id is not None:
        page = client.get_object(f"/repositories/{repo_id}")
        if page.result == "failed":
            log.error("no se pudo obtener el repo %d: code=%s %s", repo_id, page.code, page.message)
            return None
        return [RepoRef(page.rows[0]["id"], page.rows[0]["full_name"])]
    refs: list[RepoRef] = []
    for page in client.rest_pages(f"/orgs/{org}/repos", {"type": "all"}):
        if page.result == "failed":
            log.error("no se pudo listar los repos: code=%s %s", page.code, page.message)
            return None
        refs.extend(RepoRef(r["id"], r["full_name"]) for r in page.rows)
    return refs


def run(task: Optional[str] = None, repo_id: Optional[int] = None, *,
        runtime: Optional[Runtime] = None, ctx: Optional[RunContext] = None) -> int:
    """Sin `task`: corrida completa. Devuelve 0 ok, 1 fallo de ejecucion, 2 configuracion/uso."""
    if task is not None and task not in TASKS:
        log.error("tarea desconocida: %s", task)
        return 2
    if repo_id is not None and task not in PER_REPO_TASKS:
        log.error("--repo-id solo aplica a: %s", ", ".join(PER_REPO_TASKS))
        return 2

    cfg: Optional[dict[str, str]] = None
    if runtime is None:
        try:
            cfg = load_config()
        except ConfigError as e:
            log.error("configuracion invalida: %s", e)
            return 2

    ctx = ctx or RunContext.start()
    log.info("extraction_id=%d run_at=%s", ctx.extraction_id, ctx.run_at_iso)

    try:
        runtime = runtime or build_runtime(cfg)  # type: ignore[arg-type]
        tokens = TokenManager(runtime)
        tokens.client()
    except AuthError as e:
        # Sin token no hay primera pagina: ninguna escritura en extractions.
        log.error("fallo de autenticacion: %s", e)
        return 1
    except Exception:  # noqa: BLE001
        log.exception("no se pudo inicializar la corrida")
        return 1

    orchestrator = Orchestrator(ctx, runtime, tokens)
    return orchestrator.run_full() if task is None else orchestrator.run_single(task, repo_id)


class JsonFormatter(logging.Formatter):
    """Una linea JSON por registro, con la severidad que entiende Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:  # la traza va en el mismo JSON (el salto de linea queda escapado)
            message = f"{message}\n{self.formatException(record.exc_info)}"
        elif record.exc_text:
            message = f"{message}\n{record.exc_text}"
        return json.dumps({"severity": record.levelname, "message": message, "logger": record.name},
                          ensure_ascii=False)


def build_log_handler(env: Mapping[str, str] = os.environ) -> logging.Handler:
    """En Cloud Run (CLOUD_RUN_JOB definida): JSON a stdout. En local: texto legible a stderr."""
    if "CLOUD_RUN_JOB" in env:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    return handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, handlers=[build_log_handler()])
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # no pisa el entorno real
    ap = argparse.ArgumentParser(description="Recolector de metricas de GitHub (raw)")
    ap.add_argument("--task", choices=TASKS, help="ejecutar solo una tarea (por defecto: corrida completa)")
    ap.add_argument("--repo-id", type=int, help="limita una tarea por repo a este repo (id numerico)")
    args = ap.parse_args()
    sys.exit(run(args.task, args.repo_id))


if __name__ == "__main__":
    main()
