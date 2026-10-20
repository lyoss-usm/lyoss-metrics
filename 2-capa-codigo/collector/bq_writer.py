"""Carga a BigQuery con load jobs (mvp-ingesta.md, seccion 6).

JSON por lineas desde memoria, WRITE_APPEND, CREATE_NEVER, sin autodetect: BigQuery usa el
esquema de la tabla existente. Sin reintentos: si el job falla, se lanza la excepcion.
"""
import io
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery

log = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    raise TypeError(f"tipo no serializable: {type(value).__name__}")


def to_ndjson(rows: list[dict[str, Any]]) -> bytes:
    """Una fila por linea; None -> null; datetime -> ISO 8601 UTC."""
    return "\n".join(
        json.dumps(r, ensure_ascii=False, default=_json_default, separators=(",", ":"))
        for r in rows
    ).encode("utf-8")


class BigQueryWriter:
    def __init__(self, project: str, dataset: str):
        self._project = project
        self._dataset = dataset
        self._client = bigquery.Client(project=project)

    def _table_id(self, table: str) -> str:
        return f"{self._project}.{self._dataset}.{table}"

    def load_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        """Carga `rows` y espera a que el job termine; lanza excepcion si falla."""
        if not rows:
            return
        table_id = self._table_id(table)
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            autodetect=False,
        )
        started = time.monotonic()
        job = self._client.load_table_from_file(
            io.BytesIO(to_ndjson(rows)), table_id, job_config=job_config, num_retries=0
        )
        job.result(retry=None)  # lanza si el job termino con error
        log.info("load job ok: tabla=%s filas=%d duracion=%.1fs",
                 table_id, len(rows), time.monotonic() - started)

    def load_extraction_row(self, row: dict[str, Any]) -> None:
        self.load_rows("extractions", [row])
