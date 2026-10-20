"""Orquestacion de la corrida. Subpaso 5.3: auth + tarea `repos` con carga a BigQuery.

Uso (desde 2-capa-codigo/):
    python -m collector.main --task repos
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
from .tasks import run_repos

log = logging.getLogger("collector")

REQUIRED_ENV = ("PROYECTO", "DATASET", "SECRETO", "ORG", "APP_ID", "INSTALL_ID")


class ConfigError(Exception):
    pass


def load_config() -> dict[str, str]:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise ConfigError("faltan variables de entorno: " + ", ".join(missing))
    return {k: os.environ[k] for k in REQUIRED_ENV}


def run(task: str | None = None) -> int:
    """Devuelve el codigo de salida: 0 ok, 1 fallo de ejecucion, 2 configuracion."""
    try:
        cfg = load_config()
    except ConfigError as e:
        log.error("configuracion invalida: %s", e)
        return 2

    ctx = RunContext.start()
    log.info("extraction_id=%d run_at=%s dataset=%s", ctx.extraction_id, ctx.run_at_iso, cfg["DATASET"])
    if task not in (None, "repos"):
        log.error("tarea desconocida: %s", task)
        return 2

    try:
        pem = read_pem(cfg["PROYECTO"], cfg["SECRETO"])
        token = installation_token(cfg["APP_ID"], cfg["INSTALL_ID"], pem)
    except AuthError as e:
        # Sin token no hay primera pagina: no se genera fila de extractions.
        log.error("fallo de autenticacion: %s", e)
        return 1
    finally:
        pem = None

    writer = BigQueryWriter(cfg["PROYECTO"], cfg["DATASET"])
    result = run_repos(ctx, GitHubClient(token), writer, cfg["ORG"])

    print(f"extraction_id: {ctx.extraction_id}")
    print(f"tarea {result.task}: {'completa' if result.complete else 'INCOMPLETA'}")
    print(f"paginas: {result.pages} | filas repos cargadas: {result.data_rows} "
          f"| filas extractions cargadas: {result.extraction_rows}")
    if result.error:
        print(f"ultimo error: {result.error}")
    return 0 if result.complete else 1


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # no pisa el entorno real
    ap = argparse.ArgumentParser(description="Recolector de metricas de GitHub (raw)")
    ap.add_argument("--task", choices=["repos"],
                    help="ejecutar solo una tarea (por ahora solo existe `repos`)")
    sys.exit(run(ap.parse_args().task))


if __name__ == "__main__":
    main()
