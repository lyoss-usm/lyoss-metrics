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
    rate_resource: Optional[str] = None   # pool de cuota de la respuesta: core | search | ...
    rate_remaining: Optional[int] = None  # peticiones restantes en ese pool


def _failed(code: int, message: str, **extra: Any) -> Page:
    return Page([], False, None, code, message[:MAX_MESSAGE], "failed", **extra)


def _int_or_none(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


class GitHubClient:
    def __init__(self, token: str):
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        })

    def rest_pages(self, path: str, params: Optional[dict] = None, key: Optional[str] = None,
                   single_page: bool = False) -> Iterator[Page]:
        """Pagina un endpoint REST.

        key:         si la respuesta es un objeto, clave que contiene la lista de filas
                     (p. ej. "workflow_runs", "items", "views"). None = la respuesta ya es una lista.
        single_page: la tarea es de una sola pagina: has_more=False aunque exista Link rel="next".
        Sin single_page, has_more sale de la cabecera Link rel="next". Ante cualquier fallo
        emite una Page "failed" y se detiene.
        """
        yield from self._pages(path, params, key, single_page, as_object=False)

    def get_object(self, path: str) -> Page:
        """GET de un recurso unico: la Page trae rows=[objeto]."""
        return next(self._pages(path, None, None, True, as_object=True))

    def _pages(self, path: str, params: Optional[dict], key: Optional[str],
               single_page: bool, as_object: bool) -> Iterator[Page]:
        url = API + path
        query: Optional[dict] = None if as_object else {"per_page": PER_PAGE, **(params or {})}
        while url:
            try:
                resp = self._session.get(url, params=query, timeout=TIMEOUT)
            except requests.RequestException as e:
                yield _failed(0, f"{type(e).__name__}: {e}")
                return

            rate = dict(rate_resource=resp.headers.get("x-ratelimit-resource"),
                        rate_remaining=_int_or_none(resp.headers.get("x-ratelimit-remaining")))

            if not 200 <= resp.status_code < 300:
                try:
                    detail = resp.json().get("message", "")
                except (ValueError, AttributeError):
                    detail = resp.text
                yield _failed(resp.status_code, f"HTTP {resp.status_code}: {detail}", **rate)
                return

            try:
                body = resp.json()
            except ValueError:
                yield _failed(resp.status_code, "respuesta no es JSON valido", **rate)
                return

            if as_object:
                rows = [body] if isinstance(body, dict) else None
            elif key:
                if isinstance(body, dict) and body.get("incomplete_results") is True:
                    yield _failed(resp.status_code, "incomplete_results=true", **rate)
                    return
                rows = body.get(key) if isinstance(body, dict) else None
            else:
                rows = body if isinstance(body, list) else None
            if not isinstance(rows, list):
                yield _failed(resp.status_code, "forma de respuesta inesperada", **rate)
                return

            next_url = None if single_page else resp.links.get("next", {}).get("url")
            yield Page(rows, next_url is not None, None, resp.status_code, None, "succeeded", **rate)
            url, query = next_url, None  # la URL "next" ya trae sus parametros
