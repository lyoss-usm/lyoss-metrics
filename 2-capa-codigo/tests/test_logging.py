"""Formato de logs: JSON de una linea en Cloud Run, texto legible en local."""
import json
import logging
import sys

import pytest

from collector.main import JsonFormatter, build_log_handler


def record(level=logging.INFO, msg="hola %s", args=("mundo",), exc_info=None):
    return logging.LogRecord("collector.tasks", level, __file__, 1, msg, args, exc_info)


@pytest.mark.parametrize("level,severity", [
    (logging.DEBUG, "DEBUG"), (logging.INFO, "INFO"), (logging.WARNING, "WARNING"),
    (logging.ERROR, "ERROR"), (logging.CRITICAL, "CRITICAL")])
def test_severidad_por_nivel(level, severity):
    out = json.loads(JsonFormatter().format(record(level)))
    assert out == {"severity": severity, "message": "hola mundo", "logger": "collector.tasks"}


def test_una_sola_linea_por_registro():
    line = JsonFormatter().format(record(msg="linea 1\nlinea 2", args=()))
    assert "\n" not in line and json.loads(line)["message"] == "linea 1\nlinea 2"


def test_traza_de_excepcion_va_en_la_misma_linea():
    try:
        raise ValueError("explota")
    except ValueError:
        rec = record(logging.ERROR, "fallo", (), exc_info=sys.exc_info())
    line = JsonFormatter().format(rec)
    assert "\n" not in line
    message = json.loads(line)["message"]
    assert message.startswith("fallo\n") and "Traceback" in message and "ValueError: explota" in message


def test_conserva_acentos():
    assert "tamaño" in JsonFormatter().format(record(msg="tamaño", args=()))


def test_con_cloud_run_job_usa_json_en_stdout():
    handler = build_log_handler({"CLOUD_RUN_JOB": "lyoss-collector"})
    assert isinstance(handler.formatter, JsonFormatter) and handler.stream is sys.stdout


def test_sin_cloud_run_job_usa_texto_legible():
    handler = build_log_handler({})
    assert not isinstance(handler.formatter, JsonFormatter)
    text = handler.formatter.format(record())
    assert text.endswith("INFO collector.tasks: hola mundo") or "INFO collector.tasks: hola mundo" in text
    assert handler.stream is sys.stderr
