"""B) GitHubClient.rest_pages / get_object con `responses`."""
import requests

from conftest import API

URL = f"{API}/orgs/o/repos"


def pages(client, path="/orgs/o/repos", **kw):
    return list(client.rest_pages(path, **kw))


def test_link_next_encadena_paginas(client, rsps):
    next_url = f"{API}/orgs/o/repos-pagina-2"
    rsps.get(URL, json=[{"id": 1}], headers={"Link": f'<{next_url}>; rel="next", <{next_url}>; rel="last"'})
    rsps.get(next_url, json=[{"id": 2}])
    result = pages(client, params={"type": "all"})
    assert [(p.has_more, p.rows, p.result, p.code) for p in result] == [
        (True, [{"id": 1}], "succeeded", 200), (False, [{"id": 2}], "succeeded", 200)]
    assert result[0].cursor is None
    first, second = rsps.calls[0].request.url, rsps.calls[1].request.url
    assert "per_page=100" in first and "type=all" in first
    assert second == next_url  # la URL next se usa tal cual, sin anadir parametros


def test_has_more_depende_del_link_y_no_del_tamano(client, rsps):
    rsps.get(URL, json=[{"id": i} for i in range(100)])  # pagina llena, sin Link
    assert [p.has_more for p in pages(client)] == [False]


def test_single_page_ignora_link_next(client, rsps):
    rsps.get(URL, json=[{"id": 1}], headers={"Link": f'<{API}/otra>; rel="next"'})
    result = pages(client, single_page=True)
    assert len(result) == 1 and result[0].has_more is False and len(rsps.calls) == 1


def test_clave_contenedora(client, rsps):
    rsps.get(f"{API}/repos/o/r/actions/runs", json={"total_count": 1, "workflow_runs": [{"id": 9}]})
    (p,) = pages(client, "/repos/o/r/actions/runs", key="workflow_runs")
    assert p.rows == [{"id": 9}] and p.result == "succeeded"


def test_lista_vacia_es_exito(client, rsps):
    rsps.get(URL, json=[])
    (p,) = pages(client)
    assert (p.rows, p.has_more, p.result, p.code, p.message) == ([], False, "succeeded", 200, None)


def test_errores_http_sin_reintentos(client, rsps):
    for status, body in ((403, {"message": "Resource not accessible"}), (404, {"message": "Not Found"}),
                         (500, {"message": "Server Error"})):
        rsps.reset()
        rsps.get(URL, json=body, status=status)
        result = pages(client)
        assert len(result) == 1 and len(rsps.calls) == 1  # una sola peticion
        p = result[0]
        assert (p.result, p.code, p.rows, p.has_more) == ("failed", status, [], False)
        assert f"HTTP {status}" in p.message and body["message"] in p.message


def test_error_http_con_cuerpo_no_json_usa_el_texto(client, rsps):
    rsps.get(URL, body="Bad gateway", status=502)
    (p,) = pages(client)
    assert p.result == "failed" and p.code == 502 and "Bad gateway" in p.message


def test_error_en_pagina_2_detiene_el_iterador(client, rsps):
    next_url = f"{API}/pagina-2"
    rsps.get(URL, json=[{"id": 1}], headers={"Link": f'<{next_url}>; rel="next"'})
    rsps.get(next_url, json={"message": "x"}, status=500)
    result = pages(client)
    assert [p.result for p in result] == ["succeeded", "failed"] and len(rsps.calls) == 2


def test_error_de_conexion_code_0(client, rsps):
    rsps.get(URL, body=requests.exceptions.ConnectionError("sin red"))
    result = pages(client)
    assert len(result) == 1 and len(rsps.calls) == 1
    assert (result[0].result, result[0].code) == ("failed", 0)
    assert result[0].message.startswith("ConnectionError")


def test_timeout_code_0(client, rsps):
    rsps.get(URL, body=requests.exceptions.ReadTimeout("lento"))
    (p,) = pages(client)
    assert (p.result, p.code) == ("failed", 0) and "Timeout" in p.message


def test_cuerpo_no_json(client, rsps):
    rsps.get(URL, body="<html>", status=200)
    (p,) = pages(client)
    assert (p.result, p.code, p.message) == ("failed", 200, "respuesta no es JSON valido")


def test_forma_inesperada(client, rsps):
    rsps.get(URL, json={"message": "no soy lista"})
    (p,) = pages(client)
    assert (p.result, p.code, p.message) == ("failed", 200, "forma de respuesta inesperada")
    rsps.reset()
    rsps.get(URL, json=[1, 2])  # lista donde se esperaba un contenedor
    (p,) = pages(client, key="items")
    assert p.result == "failed" and p.rows == []
    rsps.reset()
    rsps.get(URL, json={"otra_clave": []})  # contenedor sin la clave
    (p,) = pages(client, key="items")
    assert p.result == "failed"


def test_incomplete_results_es_fallo_con_code_200(client, rsps):
    rsps.get(f"{API}/search/repositories", json={"incomplete_results": True, "items": [{"id": 1}]})
    (p,) = pages(client, "/search/repositories", key="items", single_page=True)
    assert (p.result, p.code, p.message, p.rows, p.has_more) == (
        "failed", 200, "incomplete_results=true", [], False)


def test_incomplete_results_false_es_exito(client, rsps):
    rsps.get(f"{API}/search/repositories", json={"incomplete_results": False, "items": [{"id": 1}]})
    (p,) = pages(client, "/search/repositories", key="items", single_page=True)
    assert p.result == "succeeded" and p.rows == [{"id": 1}]


def test_cabeceras_de_rate_limit(client, rsps):
    rsps.get(URL, json=[], headers={"x-ratelimit-resource": "core", "x-ratelimit-remaining": "4990"})
    (p,) = pages(client)
    assert (p.rate_resource, p.rate_remaining) == ("core", 4990)


def test_rate_limit_ausente_o_corrupto(client, rsps):
    rsps.get(URL, json=[])
    (p,) = pages(client)
    assert (p.rate_resource, p.rate_remaining) == (None, None)
    rsps.reset()
    rsps.get(URL, json=[], headers={"x-ratelimit-resource": "search", "x-ratelimit-remaining": "abc"})
    (p,) = pages(client)
    assert (p.rate_resource, p.rate_remaining, p.result) == ("search", None, "succeeded")


def test_rate_limit_tambien_en_paginas_fallidas(client, rsps):
    rsps.get(URL, json={"message": "x"}, status=403,
             headers={"x-ratelimit-resource": "core", "x-ratelimit-remaining": "0"})
    (p,) = pages(client)
    assert p.result == "failed" and p.rate_remaining == 0


def test_get_object(client, rsps):
    rsps.get(f"{API}/repositories/7", json={"id": 7, "full_name": "o/r"})
    p = client.get_object("/repositories/7")
    assert p.rows == [{"id": 7, "full_name": "o/r"}] and p.has_more is False
    assert "per_page" not in rsps.calls[0].request.url


def test_get_object_error(client, rsps):
    rsps.get(f"{API}/repositories/7", json={"message": "Not Found"}, status=404)
    p = client.get_object("/repositories/7")
    assert (p.result, p.code) == ("failed", 404)


def test_cabeceras_de_autenticacion(client, rsps):
    rsps.get(URL, json=[])
    pages(client)
    headers = rsps.calls[0].request.headers
    assert headers["Authorization"] == "Bearer token-de-prueba"
    assert headers["Accept"] == "application/vnd.github+json" and "X-GitHub-Api-Version" in headers
