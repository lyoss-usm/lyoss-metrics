"""E) Mapeo payload -> fila raw, y contrato contra el DDL de sql/ddl/."""
import re
from pathlib import Path

import pytest

from collector import mapping
from collector.github_client import Page

DDL_DIR = Path(__file__).resolve().parents[1] / "sql" / "ddl"
COLUMN = re.compile(r"^\s+(\w+)\s+(ARRAY<STRING>|\w+)(\s+NOT NULL)?,?\s*$")

REPO = {
    "id": 1, "name": "n", "full_name": "o/n", "visibility": "public", "description": "d", "fork": False,
    "archived": False, "disabled": False, "is_template": False, "stargazers_count": 3, "forks_count": 1,
    "open_issues_count": 2, "size": 10, "created_at": "2020-01-01T00:00:00Z",
    "updated_at": "2020-01-02T00:00:00Z", "pushed_at": "2020-01-03T00:00:00Z", "has_issues": True,
    "has_projects": True, "has_wiki": True, "has_pages": False, "has_discussions": False,
    "allow_forking": True, "language": "Python", "topics": ["a", "b"], "default_branch": "main",
    "license": {"key": "mit"},
    "custom_properties": {"active": "true", "help": "false", "display": "Nick"},
}
DAY = {"timestamp": "2026-10-01T00:00:00Z", "count": 3, "uniques": 1}


def ddl_columns(table: str) -> dict[str, bool]:
    """-> {columna: es_not_null} extraido de sql/ddl/<table>.sql"""
    cols = {}
    for line in (DDL_DIR / f"{table}.sql").read_text().splitlines():
        m = COLUMN.match(line)
        if m:
            cols[m.group(1)] = bool(m.group(3))
    return cols


@pytest.fixture
def mappers(ctx):
    page = Page([], False, None, 200, None, "succeeded")
    return {
        "repos": lambda: mapping.repo_row(REPO, ctx, "repos", 1),
        "trending_repos": lambda: mapping.trending_row(REPO, ctx, "trending_repos:stars:100", 1, "stars", 100, 1),
        "users": lambda: mapping.user_row({"id": 1, "login": "a", "type": "User"}, ctx, "users", 1),
        "actions": lambda: mapping.action_row(
            {"id": 1, "name": "ci", "status": "completed", "conclusion": "success",
             "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:01:00Z"}, ctx, "actions:7", 1, 7),
        "traffic_views": lambda: mapping.traffic_view_row(DAY, ctx, "traffic_views:7", 1, 7),
        "traffic_clones": lambda: mapping.traffic_clone_row(DAY, ctx, "traffic_clones:7", 1, 7),
        "traffic_referrers": lambda: mapping.traffic_referrer_row(
            {"referrer": "x.com", "count": 1, "uniques": 1}, ctx, "traffic_referrers:7", 1, 7),
        "traffic_paths": lambda: mapping.traffic_path_row(
            {"path": "/a", "title": "A", "count": 1, "uniques": 1}, ctx, "traffic_paths:7", 1, 7),
        "extractions": lambda: mapping.extraction_row(ctx, "repos", "/orgs/o/repos", 1, page),
    }


TABLES = ["repos", "trending_repos", "users", "actions", "traffic_views", "traffic_clones",
          "traffic_referrers", "traffic_paths", "extractions"]


def test_el_parser_del_ddl_encuentra_columnas():
    cols = ddl_columns("repos")
    assert cols["extraction_id"] is True and cols["description"] is False and "topics" in cols
    assert len(cols) == 33


@pytest.mark.parametrize("table", TABLES)
def test_contrato_claves_de_la_fila_igual_a_columnas_del_ddl(mappers, table):
    assert set(mappers[table]()) == set(ddl_columns(table))


@pytest.mark.parametrize("table", TABLES)
def test_contrato_columnas_not_null_no_son_none(mappers, table):
    row = mappers[table]()
    nulas = [c for c, not_null in ddl_columns(table).items() if not_null and row[c] is None]
    assert nulas == []


@pytest.mark.parametrize("table", TABLES)
def test_contrato_linaje(mappers, ctx, table):
    row = mappers[table]()
    assert row["extraction_id"] == ctx.extraction_id and row["run_at"] == ctx.run_at_iso
    assert row["run_at"] == "2026-10-20T01:02:03.456789+00:00"


def test_license_nula_da_license_key_none(ctx):
    for fn in (lambda r: mapping.repo_row(r, ctx, "repos", 1),
               lambda r: mapping.trending_row(r, ctx, "t", 1, "stars", 100, 1)):
        assert fn({**REPO, "license": None})["license_key"] is None
        assert fn({k: v for k, v in REPO.items() if k != "license"})["license_key"] is None


def test_topics_ausente_o_nulo_da_lista_vacia(ctx):
    sin_topics = {k: v for k, v in REPO.items() if k != "topics"}
    assert mapping.repo_row(sin_topics, ctx, "repos", 1)["topics"] == []
    assert mapping.repo_row({**REPO, "topics": None}, ctx, "repos", 1)["topics"] == []
    assert mapping.trending_row(sin_topics, ctx, "t", 1, "stars", 100, 1)["topics"] == []


def test_campos_nulos_de_la_api_quedan_none(ctx):
    row = mapping.repo_row({**REPO, "description": None, "language": None, "pushed_at": None}, ctx, "repos", 1)
    assert (row["description"], row["language"], row["pushed_at"]) == (None, None, None)
    row = mapping.action_row({"id": 1, "conclusion": None}, ctx, "actions:7", 1, 7)
    assert row["conclusion"] is None
    row = mapping.user_row({"id": 1}, ctx, "users", 1)
    assert row["login"] is None and row["type"] is None


def test_custom_properties(ctx):
    row = mapping.repo_row(REPO, ctx, "repos", 1)
    assert (row["custom_active"], row["custom_help"], row["custom_display"]) == ("true", "false", "Nick")
    sin = {k: v for k, v in REPO.items() if k != "custom_properties"}
    row = mapping.repo_row(sin, ctx, "repos", 1)
    assert (row["custom_active"], row["custom_help"], row["custom_display"]) == (None, None, None)
    row = mapping.repo_row({**REPO, "custom_properties": {"active": True, "help": None}}, ctx, "repos", 1)
    assert (row["custom_active"], row["custom_help"]) == ("true", None)


def test_valores_pasan_sin_transformar(ctx):
    row = mapping.repo_row(REPO, ctx, "repos", 3)
    assert row["page_number"] == 3 and row["task"] == "repos" and row["id"] == 1
    assert row["stargazers_count"] == 3 and row["created_at"] == "2020-01-01T00:00:00Z"
    assert row["license_key"] == "mit" and row["topics"] == ["a", "b"]


def test_trending_solo_top_ord_es_calculado(ctx):
    row = mapping.trending_row(REPO, ctx, "trending_repos:stars:100", 1, "stars", 100, 42)
    assert (row["attribute"], row["top_limit"], row["top_ord"]) == ("stars", 100, 42)
    assert row["stargazers_count"] == REPO["stargazers_count"]


def test_action_repo_id_viene_del_argumento_no_de_la_respuesta(ctx):
    run = {"id": 1, "repository": {"id": 999}}
    assert mapping.action_row(run, ctx, "actions:7", 1, 7)["repo_id"] == 7


def test_extraction_row_refleja_la_pagina(ctx):
    page = Page([], True, None, 403, "no", "failed")
    row = mapping.extraction_row(ctx, "repos", "/e", 2, page)
    assert (row["page_number"], row["has_more"], row["cursor"], row["code"], row["message"], row["result"],
            row["endpoint"], row["task"]) == (2, True, None, 403, "no", "failed", "/e", "repos")
