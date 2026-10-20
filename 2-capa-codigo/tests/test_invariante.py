"""A) execute_task: invariante de escritura por pagina y definicion de tarea completa."""
import itertools

import pytest

from collector.tasks import execute_task
from conftest import FakeWriter, TrackedPages, failed_page, ok_page, row_mapper

TASK = "t"


def run(ctx, writer, pages, mapper=row_mapper):
    tracked = pages if isinstance(pages, TrackedPages) else TrackedPages(pages)
    result = execute_task(ctx, writer, TASK, "/e", "tabla", tracked, mapper)
    return result, tracked


def tables(writer):
    return [(c.table, c.raised) for c in writer.calls]


def definicion_completa(extraction_rows, task=TASK) -> bool:
    """Definicion de politicas.md, implementada de forma independiente:
    1. todas succeeded, 2. page_number consecutivos desde 1, 3. la ultima con has_more=false."""
    rows = sorted((r for r in extraction_rows if r["task"] == task), key=lambda r: r["page_number"])
    if not rows:
        return False
    if any(r["result"] != "succeeded" for r in rows):
        return False
    if [r["page_number"] for r in rows] != list(range(1, len(rows) + 1)):
        return False
    return rows[-1]["has_more"] is False


# --- Escenarios puntuales -----------------------------------------------------------------------
def test_una_pagina_con_filas(ctx):
    w = FakeWriter()
    result, _ = run(ctx, w, [ok_page(["a", "b"])])
    assert tables(w) == [("tabla", False), ("extractions", False)]
    assert result.complete and result.pages == 1
    assert (result.data_rows, result.extraction_rows, result.error) == (2, 1, None)
    row = w.extraction_rows[0]
    assert (row["page_number"], row["has_more"], row["result"], row["endpoint"]) == (1, False, "succeeded", "/e")


def test_tres_paginas_alterna_datos_y_extractions(ctx):
    w = FakeWriter()
    result, _ = run(ctx, w, [ok_page(["a"], True), ok_page(["b"], True), ok_page(["c"], False)])
    assert tables(w) == [("tabla", False), ("extractions", False)] * 3
    assert [r["page_number"] for r in w.extraction_rows] == [1, 2, 3]
    assert [r["has_more"] for r in w.extraction_rows] == [True, True, False]
    assert result.complete and result.data_rows == 3 and result.extraction_rows == 3


def test_pagina_sin_filas_no_carga_datos(ctx):
    w = FakeWriter()
    result, _ = run(ctx, w, [ok_page([])])
    assert tables(w) == [("extractions", False)]
    assert result.complete and result.data_rows == 0 and result.extraction_rows == 1


def test_falla_la_pagina_1(ctx):
    w = FakeWriter()
    result, _ = run(ctx, w, [failed_page(403, "nope")])
    assert tables(w) == [("extractions", False)]
    row = w.extraction_rows[0]
    assert (row["result"], row["code"], row["message"], row["page_number"]) == ("failed", 403, "nope", 1)
    assert not result.complete and "403" in result.error and result.extraction_rows == 1


def test_falla_la_pagina_2_de_3_y_la_3_no_se_pide(ctx):
    w = FakeWriter()
    pages = TrackedPages([ok_page(["a"], True), failed_page(500, "x"), ok_page(["c"], False)])
    result, tracked = run(ctx, w, pages)
    assert tracked.pulled == 2  # el iterador no se consume mas
    assert tables(w) == [("tabla", False), ("extractions", False), ("extractions", False)]
    assert [r["result"] for r in w.extraction_rows] == ["succeeded", "failed"]
    assert not result.complete and result.pages == 2


def test_falla_la_carga_de_datos_no_escribe_extractions_de_esa_pagina(ctx):
    w = FakeWriter(fail_on_table="tabla")
    pages = TrackedPages([ok_page(["a"], True), ok_page(["b"], False)])
    result, tracked = run(ctx, w, pages)
    assert tables(w) == [("tabla", True)]  # ni extractions, ni pagina siguiente
    assert tracked.pulled == 1
    assert w.extraction_rows == []
    assert not result.complete and "carga de datos" in result.error and result.data_rows == 0


def test_falla_la_carga_de_extractions_despues_de_cargar_datos(ctx):
    w = FakeWriter(fail_on_table="extractions")
    pages = TrackedPages([ok_page(["a"], True), ok_page(["b"], False)])
    result, tracked = run(ctx, w, pages)
    assert tables(w) == [("tabla", False), ("extractions", True)]
    assert tracked.pulled == 1  # termina la tarea
    assert not result.complete and result.data_rows == 1 and result.extraction_rows == 0
    assert "extractions" in result.error


def test_el_mapeo_lanza_excepcion(ctx):
    def mapper_roto(raw, c, t, n):
        raise KeyError("id")

    w = FakeWriter()
    result, _ = run(ctx, w, [ok_page([{"sin": "id"}])], mapper=mapper_roto)
    assert w.calls == []  # nada cargado, ni datos ni extractions
    assert not result.complete and "carga de datos" in result.error and "KeyError" in result.error


def test_falla_el_registro_de_la_fila_failed(ctx):
    w = FakeWriter(fail_when=lambda table, rows: table == "extractions" and rows[0]["result"] == "failed")
    result, _ = run(ctx, w, [ok_page(["a"], True), failed_page(500, "x")])
    assert tables(w) == [("tabla", False), ("extractions", False), ("extractions", True)]
    assert not result.complete
    assert result.extraction_rows == 1  # solo la succeeded de la pagina 1 quedo registrada
    assert "500" in result.error


def test_iterador_vacio_no_es_completa(ctx):
    w = FakeWriter()
    result, _ = run(ctx, w, [])
    assert w.calls == [] and not result.complete and result.pages == 0


# --- Propiedad: result.complete == definicion de politicas.md ------------------------------------
def _escenarios():
    """Todas las combinaciones: n paginas (1-4), pagina fallida de la API (ninguna o k),
    paginas vacias, y un fallo del writer (ninguno, llamada N, o tabla completa)."""
    for n in range(1, 5):
        for api_fail in [None, *range(1, n + 1)]:
            for empty in [(), (1,), (n,)]:
                if any(e > n for e in empty):
                    continue
                writer_faults = [{}, {"fail_on_table": "tabla"}, {"fail_on_table": "extractions"}]
                writer_faults += [{"fail_on_call": k} for k in range(1, 2 * n + 2)]
                for fault in writer_faults:
                    yield n, api_fail, empty, fault


def _paginas(n, api_fail, empty):
    pages = []
    for k in range(1, n + 1):
        if k == api_fail:
            pages.append(failed_page(500, "x"))
            break  # el cliente real se detiene tras una pagina fallida
        pages.append(ok_page([] if k in empty else [f"r{k}"], has_more=k < n))
    return pages


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_propiedad_complete_coincide_con_la_definicion(ctx, n):
    count = 0
    for sn, api_fail, empty, fault in _escenarios():
        if sn != n:
            continue
        w = FakeWriter(**fault)
        result, _ = run(ctx, w, _paginas(n, api_fail, empty))
        esperado = definicion_completa(w.extraction_rows)
        assert result.complete == esperado, (n, api_fail, empty, fault)
        count += 1
    assert count > 0


def test_propiedad_orden_de_escritura_por_pagina(ctx):
    """Una fila succeeded de la pagina k solo existe si sus datos (si los tenia) ya estaban cargados antes."""
    for n, api_fail, empty, fault in _escenarios():
        w = FakeWriter(**fault)
        run(ctx, w, _paginas(n, api_fail, empty))
        for idx, call in enumerate(w.calls):
            if call.table != "extractions" or call.raised:
                continue
            row = call.rows[0]
            if row["result"] != "succeeded":
                continue
            k = row["page_number"]
            if k in empty:
                assert not any(c.table == "tabla" and c.rows[0]["page_number"] == k for c in w.calls)
            else:
                previos = [c for c in w.calls[:idx]
                           if c.table == "tabla" and not c.raised and c.rows[0]["page_number"] == k]
                assert previos, (n, api_fail, empty, fault, k)


def test_propiedad_pagina_con_datos_fallidos_nunca_tiene_extractions(ctx):
    for n, api_fail, empty, fault in _escenarios():
        w = FakeWriter(**fault)
        run(ctx, w, _paginas(n, api_fail, empty))
        fallidas = {c.rows[0]["page_number"] for c in w.calls if c.table == "tabla" and c.raised}
        registradas = {r["page_number"] for r in w.extraction_rows}
        assert not (fallidas & registradas), (n, api_fail, empty, fault)
