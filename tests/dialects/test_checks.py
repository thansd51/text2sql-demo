import re

import pytest
import sqlglot

from text2sql.dialects import get_adapter

HANGUL = re.compile(r"[가-힣]")


def violations(db_type: str, db_version: str, sql: str) -> list[str]:
    adapter = get_adapter(db_type, db_version)
    return adapter.check(sqlglot.parse_one(sql, read=adapter.sqlglot_dialect))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t WHERE b = ''",
        "SELECT a FROM t WHERE b <> ('')",
        "SELECT a FROM t WHERE b LIKE ''",
        "SELECT a FROM t WHERE b IN ('', 'x')",
        "SELECT a FROM t OFFSET 5 ROWS",
        "SELECT CAST(a AS VARCHAR2) FROM t",
    ],
)
def test_oracle_pitfalls_are_reported_in_korean(sql: str) -> None:
    result = violations("oracle", "19c", sql)

    assert result, sql
    assert all(HANGUL.search(message) for message in result)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a FROM t WHERE b IS NULL",
        "SELECT a FROM t WHERE b = 'x'",
        "SELECT CAST(a AS VARCHAR2(100)) FROM t",
        "SELECT '' AS e FROM t",
        "SELECT a FROM t FETCH FIRST 5 ROWS ONLY",
    ],
)
def test_normal_oracle_queries_have_no_violations(sql: str) -> None:
    assert violations("oracle", "19c", sql) == []


def test_fetch_first_is_a_violation_before_oracle_12c() -> None:
    sql = "SELECT a FROM t FETCH FIRST 5 ROWS ONLY"

    assert violations("oracle", "12c", sql) == []
    for db_version in ("9i", "11g", "11.2"):
        result = violations("oracle", db_version, sql)
        assert len(result) == 1, db_version
        assert "FETCH FIRST" in result[0]


def test_postgresql_has_no_dialect_specific_violations() -> None:
    for sql in ("SELECT a FROM t WHERE b = ''", "SELECT a FROM t OFFSET 5"):
        assert violations("postgresql", "14", sql) == []
