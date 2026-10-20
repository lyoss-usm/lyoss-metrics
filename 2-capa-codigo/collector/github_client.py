"""Cliente REST de GitHub: una Page por llamada, sin reintentos."""
from dataclasses import dataclass
from typing import Any, Iterator, Optional

import requests

from .github_auth import API, API_VERSION

PER_PAGE = 100
TIMEOUT = (10, 30)  # (connect, read) en segundos
MAX_MESSAGE = 500


@dataclass
class Page:
    rows: list[Any]          # filas crudas de la API (vacio si fallo)
    has_more: bool
    cursor: Optional[str]    # None en REST
    code: int                # HTTP; 0 si no hubo respuesta
    message: Optional[str]   # None si no hay error
    result: str              # "succeeded" | "failed"


def _failed(code: int, message: str) -> Page:
    return Page([], False, None, code, message[:MAX_MESSAGE], "failed")


class GitHubClient:
    def __init__(self, token: str):
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        })

    def rest_pages(self, path: str, params: Optional[dict] = None) -> Iterator[Page]:
        """Pagina un endpoint REST que devuelve una lista.

        has_more sale de la cabecera Link rel="next". Ante cualquier fallo emite
        una Page "failed" y se detiene.
        """
        url = API + path
        query: Optional[dict] = {"per_page": PER_PAGE, **(params or {})}
        while url:
            try:
                resp = self._session.get(url, params=query, timeout=TIMEOUT)
            except requests.RequestException as e:
                yield _failed(0, f"{type(e).__name__}: {e}")
                return

            if not 200 <= resp.status_code < 300:
                try:
                    detail = resp.json().get("message", "")
                except (ValueError, AttributeError):
                    detail = resp.text
                yield _failed(resp.status_code, f"HTTP {resp.status_code}: {detail}")
                return

            try:
                rows = resp.json()
            except ValueError:
                yield _failed(resp.status_code, "respuesta no es JSON valido")
                return
            if not isinstance(rows, list):
                yield _failed(resp.status_code, "se esperaba una lista JSON")
                return

            next_url = resp.links.get("next", {}).get("url")
            yield Page(rows, next_url is not None, None, resp.status_code, None, "succeeded")
            url, query = next_url, None  # la URL "next" ya trae sus parametros
