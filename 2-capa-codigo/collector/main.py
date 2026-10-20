"""Orquestacion de la corrida. Subpaso 5.4a: tareas REST ejecutables de a una.

Uso (desde 2-capa-codigo/):
    python -m collector.main --task repos
    python -m collector.main --task users
    python -m collector.main --task trending_repos
    python -m collector.main --task actions [--repo-id N]
    python -m collector.main --task traffic_views|traffic_clones|traffic_referrers|traffic_paths [--repo-id N]

Las tareas por repo sin --repo-id se ejecutan para todos los repos de la organizacion
(la lista se obtiene de la API y nunca de BigQuery).
"""
import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .bq_writer import BigQueryWriter
from .context import RunContext
from .github_auth import AuthError, installation_token, read_pem
from .github_client import GitHubClient
from .tasks import (PER_REPO_TASKS, RepoRef, TaskResult, run_actions, run_repos, run_traffic,
                    run_trending_repos, run_users)

log = logging.getLogger("collector")

REQUIRED_ENV = ("PROYECTO", "DATASET", "SECRETO", "ORG", "APP_ID", "INSTALL_ID")
TASKS = ("repos", "users", "trending_repos", *PER_REPO_TASKS)


class ConfigError(Exception):
    pass


def load_config() -> dict[str, str]:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise ConfigError("faltan variables de entorno: " + ", ".join(missing))
    return {k: os.environ[k] for k in REQUIRED_ENV}


def resolve_repos(client: GitHubClient, org: str, repo_id: int | None) -> list[RepoRef] | None:
    """Repos sobre los que correr una tarea por repo. None si no se pudo obtener la lista.

    Solo para ejecutar una tarea suelta: no carga nada a BigQuery. En la corrida completa
    la lista sale de la tarea `repos`.
    """
    refs: list[RepoRef] = []
    if repo_id is not None:
        page = client.get_object(f"/repositories/{repo_id}")
        if page.result == "failed":
            log.error("no se pudo obtener el repo %d: code=%s %s", repo_id, page.code, page.message)
            return None
        return [RepoRef(page.rows[0]["id"], page.rows[0]["full_name"])]
    for page in client.rest_pages(f"/orgs/{org}/repos", {"type": "all"}):
        if page.result == "failed":
            log.error("no se pudo listar los repos: code=%s %s", page.code, page.message)
            return None
        refs.extend(RepoRef(r["id"], r["full_name"]) for r in page.rows)
    return refs


def run(task: str | None = None, repo_id: int | None = None) -> int:
    """Devuelve el codigo de salida: 0 ok, 1 fallo de ejecucion, 2 configuracion/uso."""
    task = task or "repos"
    if task not in TASKS:
        log.error("tarea desconocida: %s", task)
        return 2
    if repo_id is not None and task not in PER_REPO_TASKS:
        log.error("--repo-id solo aplica a: %s", ", ".join(PER_REPO_TASKS))
        return 2
    try:
        cfg = load_config()
    except ConfigError as e:
        log.error("configuracion invalida: %s", e)
        return 2

    ctx = RunContext.start()
    log.info("extraction_id=%d run_at=%s dataset=%s", ctx.extraction_id, ctx.run_at_iso, cfg["DATASET"])

    try:
        pem = read_pem(cfg["PROYECTO"], cfg["SECRETO"])
        token = installation_token(cfg["APP_ID"], cfg["INSTALL_ID"], pem)
    except AuthError as e:
        # Sin token no hay primera pagina: no se genera fila de extractions.
        log.error("fallo de autenticacion: %s", e)
        return 1
    finally:
        pem = None

    client = GitHubClient(token)
    writer = BigQueryWriter(cfg["PROYECTO"], cfg["DATASET"])

    results: list[TaskResult] = []
    if task == "repos":
        results.append(run_repos(ctx, client, writer, cfg["ORG"]))
    elif task == "users":
        results.append(run_users(ctx, client, writer, cfg["ORG"]))
    elif task == "trending_repos":
        results.append(run_trending_repos(ctx, client, writer))
    else:
        repos = resolve_repos(client, cfg["ORG"], repo_id)
        if repos is None:
            return 1
        for repo in repos:
            if task == "actions":
                results.append(run_actions(ctx, client, writer, repo))
            else:
                results.append(run_traffic(ctx, client, writer, repo, task))

    print(f"extraction_id: {ctx.extraction_id}")
    for r in results:
        print(f"{r.task}: {'completa' if r.complete else 'INCOMPLETA'} | paginas={r.pages} "
              f"| filas={r.data_rows} | extractions={r.extraction_rows}"
              + (f" | error: {r.error}" if r.error else ""))
    return 0 if all(r.complete for r in results) else 1


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # no pisa el entorno real
    ap = argparse.ArgumentParser(description="Recolector de metricas de GitHub (raw)")
    ap.add_argument("--task", choices=TASKS, help="tarea a ejecutar (por defecto: repos)")
    ap.add_argument("--repo-id", type=int, help="limita una tarea por repo a este repo (id numerico)")
    args = ap.parse_args()
    sys.exit(run(args.task, args.repo_id))


if __name__ == "__main__":
    main()
