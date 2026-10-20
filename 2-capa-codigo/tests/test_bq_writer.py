"""D) BigQueryWriter con un cliente de BigQuery falso (sin credenciales ni red)."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from google.cloud import bigquery

from collector import bq_writer
from collector.bq_writer import BigQueryWriter, to_ndjson


class FakeJob:
    def __init__(self, events, error=None):
        self.events, self.error, self.result_kwargs = events, error, None

    def result(self, **kwargs):
        self.result_kwargs = kwargs
        self.events.append("result")
        if self.error:
            raise self.error


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, project=None):
        self.project, self.events, self.submissions, self.error = project, [], [], None
        FakeClient.instances.append(self)

    def load_table_from_file(self, file_obj, table_id, job_config=None, num_retries=None):
        self.events.append("submit")
        job = FakeJob(self.events, self.error)
        self.submissions.append({"body": file_obj.read().decode(), "table_id": table_id,
                                 "config": job_config, "num_retries": num_retries, "job": job})
        return job


@pytest.fixture
def bq(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(bq_writer.bigquery, "Client", FakeClient)
    writer = BigQueryWriter("proy", "raw_test")
    return writer, FakeClient.instances[0]


def test_destino_y_configuracion_del_job(bq):
    writer, client = bq
    writer.load_rows("repos", [{"id": 1}])
    (sub,) = client.submissions
    cfg = sub["config"]
    assert sub["table_id"] == "proy.raw_test.repos"
    assert cfg.source_format == bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
    assert cfg.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert cfg.create_disposition == bigquery.CreateDisposition.CREATE_NEVER
    assert cfg.autodetect is False and cfg.schema is None  # usa el esquema de la tabla existente
    assert sub["num_retries"] == 0 and sub["job"].result_kwargs == {"retry": None}  # sin reintentos


def test_espera_el_resultado_del_job_antes_de_volver(bq):
    writer, client = bq
    writer.load_rows("repos", [{"id": 1}])
    assert client.events == ["submit", "result"]


def test_propaga_la_excepcion_si_el_job_falla(bq):
    writer, client = bq
    client.error = RuntimeError("quota exceeded")
    with pytest.raises(RuntimeError, match="quota exceeded"):
        writer.load_rows("repos", [{"id": 1}])
    assert client.events == ["submit", "result"]  # llego a esperar el job
    assert len(client.submissions) == 1  # no reintenta


def test_sin_filas_no_lanza_job(bq):
    writer, client = bq
    writer.load_rows("repos", [])
    assert client.submissions == []


def test_load_extraction_row_apunta_a_extractions(bq):
    writer, client = bq
    writer.load_extraction_row({"extraction_id": 1, "result": "succeeded"})
    assert client.submissions[0]["table_id"] == "proy.raw_test.extractions"
    assert json.loads(client.submissions[0]["body"]) == {"extraction_id": 1, "result": "succeeded"}


def test_json_por_lineas_con_null_y_listas(bq):
    writer, client = bq
    writer.load_rows("repos", [{"id": 1, "description": None, "topics": []}, {"id": 2, "topics": ["a"]}])
    lines = client.submissions[0]["body"].split("\n")
    assert [json.loads(line) for line in lines] == [
        {"id": 1, "description": None, "topics": []}, {"id": 2, "topics": ["a"]}]
    assert '"description":null' in lines[0]


def test_timestamps_en_iso_utc():
    utc = datetime(2026, 10, 20, 1, 2, 3, 456789, tzinfo=timezone.utc)
    otra_zona = datetime(2026, 10, 19, 22, 2, 3, 456789, tzinfo=timezone(timedelta(hours=-3)))
    ingenuo = datetime(2026, 10, 20, 1, 2, 3, 456789)
    for value in (utc, otra_zona, ingenuo):  # el ingenuo se interpreta como UTC
        (row,) = [json.loads(to_ndjson([{"t": value}]))]
        assert row["t"] == "2026-10-20T01:02:03.456789+00:00"


def test_tipo_no_serializable_lanza():
    with pytest.raises(TypeError):
        to_ndjson([{"x": {1, 2}}])


def test_acentos_se_conservan():
    assert "tamaño" in to_ndjson([{"d": "tamaño"}]).decode("utf-8")
