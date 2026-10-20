"""Dobles compartidos por los tests. Sin red, sin credenciales de GCP."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import pytest
import responses

from collector.context import RunContext
from collector.github_client import GitHubClient, Page

API = "https://api.github.com"


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch):
    """Ningun test depende del entorno real."""
    for key in ("PROYECTO", "DATASET", "SECRETO", "ORG", "APP_ID", "INSTALL_ID", "GH_TOKEN"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def ctx() -> RunContext:
    run_at = datetime(2026, 10, 20, 1, 2, 3, 456789, tzinfo=timezone.utc)
    return RunContext(run_at=run_at, extraction_id=1792458123456789)


@pytest.fixture
def rsps():
    """HTTP simulado: cualquier URL no registrada falla (no hay red posible)."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient("token-de-prueba")


# --- Writer falso -------------------------------------------------------------------------------
@dataclass
class Call:
    table: str
    rows: list[dict[str, Any]]
    raised: bool


class FakeWriter:
    """Misma interfaz que BigQueryWriter. TODAS las llamadas (datos y extractions) quedan en
    una sola lista ordenada, `calls`; las que lanzaron excepcion llevan raised=True.

    fail_on_call:  numero de llamada (desde 1) que lanza.
    fail_on_table: toda llamada a esa tabla lanza.
    fail_when:     predicado (table, rows) -> bool para casos mas finos.
    """

    def __init__(self, fail_on_call: Optional[int] = None, fail_on_table: Optional[str] = None,
                 fail_when: Optional[Callable[[str, list], bool]] = None):
        self.calls: list[Call] = []
        self.fail_on_call = fail_on_call
        self.fail_on_table = fail_on_table
        self.fail_when = fail_when

    def load_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        number = len(self.calls) + 1
        raised = (number == self.fail_on_call
                  or table == self.fail_on_table
                  or bool(self.fail_when and self.fail_when(table, rows)))
        self.calls.append(Call(table, list(rows), raised))
        if raised:
            raise RuntimeError(f"fallo simulado en la llamada {number} ({table})")

    def load_extraction_row(self, row: dict[str, Any]) -> None:
        self.load_rows("extractions", [row])

    # Vistas de conveniencia sobre la lista unica
    @property
    def loaded(self) -> list[Call]:
        return [c for c in self.calls if not c.raised]

    @property
    def data_calls(self) -> list[Call]:
        return [c for c in self.calls if c.table != "extractions"]

    @property
    def extraction_rows(self) -> list[dict[str, Any]]:
        """Filas de extractions que quedaron realmente cargadas, en orden."""
        return [r for c in self.loaded if c.table == "extractions" for r in c.rows]


# --- Paginas ------------------------------------------------------------------------------------
def ok_page(rows: list[Any], has_more: bool = False, **kw: Any) -> Page:
    return Page(rows, has_more, None, 200, None, "succeeded", **kw)


def failed_page(code: int = 500, message: str = "boom") -> Page:
    return Page([], False, None, code, message, "failed")


class TrackedPages:
    """Iterador que cuenta cuantas paginas se le han pedido (el ejecutor no debe pedir de mas)."""

    def __init__(self, pages: list[Page]):
        self._pages = list(pages)
        self.pulled = 0

    def __iter__(self):
        return self

    def __next__(self) -> Page:
        if self.pulled >= len(self._pages):
            raise StopIteration
        page = self._pages[self.pulled]
        self.pulled += 1
        return page


def row_mapper(raw: list[Any], ctx: RunContext, task: str, page_number: int) -> list[dict[str, Any]]:
    """Mapeador de prueba: una fila por elemento, con la pagina a la que pertenece."""
    return [{"extraction_id": ctx.extraction_id, "task": task, "page_number": page_number, "v": r}
            for r in raw]
