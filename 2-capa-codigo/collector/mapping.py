"""Payload de la API -> filas raw. Sin campos calculados."""
from typing import Any, Optional

from .context import RunContext


def _custom_property(props: Optional[dict], key: str) -> Optional[str]:
    """Las propiedades personalizadas son STRING en raw; None si no estan definidas."""
    value = (props or {}).get(key)
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def repo_row(repo: dict[str, Any], ctx: RunContext, task: str, page_number: int) -> dict[str, Any]:
    """Fila de la tabla `repos` (columnas en el orden de borrador-tablas-raw.md)."""
    return {
        "extraction_id": ctx.extraction_id,
        "run_at": ctx.run_at_iso,
        "task": task,
        "page_number": page_number,
        "id": repo["id"],
        "name": repo.get("name"),
        "full_name": repo.get("full_name"),
        "visibility": repo.get("visibility"),
        "description": repo.get("description"),
        "fork": repo.get("fork"),
        "archived": repo.get("archived"),
        "disabled": repo.get("disabled"),
        "is_template": repo.get("is_template"),
        "stargazers_count": repo.get("stargazers_count"),
        "forks_count": repo.get("forks_count"),
        "open_issues_count": repo.get("open_issues_count"),
        "size": repo.get("size"),
        "created_at": repo.get("created_at"),
        "updated_at": repo.get("updated_at"),
        "pushed_at": repo.get("pushed_at"),
        "has_issues": repo.get("has_issues"),
        "has_projects": repo.get("has_projects"),
        "has_wiki": repo.get("has_wiki"),
        "has_pages": repo.get("has_pages"),
        "has_discussions": repo.get("has_discussions"),
        "allow_forking": repo.get("allow_forking"),
        "language": repo.get("language"),
        "topics": repo.get("topics") or [],
        "default_branch": repo.get("default_branch"),
        "license_key": (repo.get("license") or {}).get("key"),
        "custom_active": _custom_property(repo.get("custom_properties"), "active"),
        "custom_help": _custom_property(repo.get("custom_properties"), "help"),
        "custom_display": _custom_property(repo.get("custom_properties"), "display"),
    }


def extraction_row(ctx: RunContext, task: str, endpoint: str, page_number: int, page) -> dict[str, Any]:
    """Fila de la tabla `extractions` para una pagina."""
    return {
        "extraction_id": ctx.extraction_id,
        "run_at": ctx.run_at_iso,
        "task": task,
        "endpoint": endpoint,
        "page_number": page_number,
        "has_more": page.has_more,
        "cursor": page.cursor,
        "code": page.code,
        "message": page.message,
        "result": page.result,
    }
