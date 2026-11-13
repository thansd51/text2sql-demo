import re

import pytest

from text2sql.dialects import RowLimitError, get_adapter

HANGUL = re.compile(r"[가-힣]")


# ---- PostgreSQL: LIMIT ----


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT a FROM t", "SELECT a FROM t LIMIT 100"),
        ("SELECT a FROM t ORDER BY a", "SELECT a FROM t ORDER BY a LIMIT 100"),
        ("SELECT a FROM t LIMIT 5", "SELECT a FROM t LIMIT 5"),
        ("SELECT a FROM t LIMIT 500", "SELECT a FROM t LIMIT 100"),
        ("SELECT a FROM t LIMIT 5 OFFSET 2", "SELECT a FROM t LIMIT 5 OFFSET 2"),
        ("SELECT a FROM t LIMIT 500 OFFSET 2", "SELECT a FROM t LIMIT 100 OFFSET 2"),
        ("SELECT a FROM t FETCH FIRST 500 ROWS ONLY", "SELECT a FROM t LIMIT 100"),
        (
            "SELECT a FROM t UNION SELECT a FROM s",
            "SELECT a FROM t UNION SELECT a FROM s LIMIT 100",
        ),
        (
            "WITH c AS (SELECT a FROM t) SELECT a FROM c",
            "WITH c AS (SELECT a FROM t) SELECT a FROM c LIMIT 100",
        ),
    ],
)
def test_postgresql_uses_limit_and_keeps_the_smaller(sql: str, expected: str) -> None:
    assert get_adapter("postgresql", "14").apply_row_limit(sql, 100) == expected


def test_postgresql_ignores_db_version_for_row_limit() -> None:
    sql = "SELECT a FROM t"

    assert (
        get_adapter("postgresql", "9.6").apply_row_limit(sql, 10)
        == get_adapter("postgresql", "16").apply_row_limit(sql, 10)
        == "SELECT a FROM t LIMIT 10"
    )


# ---- Oracle: 버전과 무관하게 ROWNUM (docs/design.md) ----


@pytest.mark.parametrize(
    "db_version", ["9i", "11g", "11.2", "12c", "12.2", "19c", "23ai"]
)
def test_oracle_uses_rownum_for_every_version(db_version: str) -> None:
    result = get_adapter("oracle", db_version).apply_row_limit("SELECT a FROM t", 100)

    assert result == "SELECT * FROM (SELECT a FROM t) WHERE ROWNUM <= 100"
    assert "FETCH" not in result


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "SELECT a FROM t ORDER BY a",
            "SELECT * FROM (SELECT a FROM t ORDER BY a) WHERE ROWNUM <= 100",
        ),
        (
            "SELECT a FROM t UNION SELECT a FROM s",
            "SELECT * FROM (SELECT a FROM t UNION SELECT a FROM s) WHERE ROWNUM <= 100",
        ),
        # WITH는 바깥으로 올라간다
        (
            "WITH c AS (SELECT a FROM t) SELECT a FROM c ORDER BY a",
            "WITH c AS (SELECT a FROM t) SELECT * FROM (SELECT a FROM c ORDER BY a) WHERE ROWNUM <= 100",
        ),
        # 질의 자신의 제한이 더 작으면 그 값을, 더 크면 서버 값을 쓴다
        (
            "SELECT a FROM t FETCH FIRST 5 ROWS ONLY",
            "SELECT * FROM (SELECT a FROM t) WHERE ROWNUM <= 5",
        ),
        (
            "SELECT a FROM t FETCH FIRST 500 ROWS ONLY",
            "SELECT * FROM (SELECT a FROM t) WHERE ROWNUM <= 100",
        ),
        (
            "WITH c AS (SELECT a FROM t) SELECT a FROM c ORDER BY a FETCH FIRST 5 ROWS ONLY",
            "WITH c AS (SELECT a FROM t) SELECT * FROM (SELECT a FROM c ORDER BY a) WHERE ROWNUM <= 5",
        ),
    ],
)
def test_oracle_rownum_wrapping(sql: str, expected: str) -> None:
    assert get_adapter("oracle", "19c").apply_row_limit(sql, 100) == expected


def test_oracle_keeps_the_llm_written_rownum_inside() -> None:
    sql = "SELECT * FROM (SELECT a FROM t ORDER BY a) WHERE ROWNUM <= 3"

    result = get_adapter("oracle", "11g").apply_row_limit(sql, 100)

    assert result == f"SELECT * FROM ({sql}) WHERE ROWNUM <= 100"


# ---- 공통 오류 ----


@pytest.mark.parametrize("db_type", ["oracle", "postgresql"])
@pytest.mark.parametrize("max_rows", [0, -1, True, 1.5, "10", None])
def test_invalid_max_rows_is_rejected_in_korean(db_type: str, max_rows: object) -> None:
    with pytest.raises(RowLimitError) as info:
        get_adapter(db_type, "19c").apply_row_limit("SELECT a FROM t", max_rows)  # type: ignore[arg-type]

    assert info.value.code == "ROW_LIMIT_ERROR"
    assert HANGUL.search(info.value.message)


@pytest.mark.parametrize("db_type", ["oracle", "postgresql"])
@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM t",
        "SELECT a FROM t; SELECT b FROM t",
        "SELEC FROM",
        "",
        "CREATE VIEW v AS SELECT a FROM t",
    ],
)
def test_non_select_or_unparsable_sql_is_rejected(db_type: str, sql: str) -> None:
    with pytest.raises(RowLimitError) as info:
        get_adapter(db_type, "19c").apply_row_limit(sql, 100)

    assert HANGUL.search(info.value.message)


@pytest.mark.parametrize(
    ("db_type", "sql"),
    [
        ("postgresql", "SELECT a FROM t LIMIT x"),
        ("postgresql", "SELECT a FROM t LIMIT 5 PERCENT"),
        ("oracle", "SELECT a FROM t FETCH FIRST 5 PERCENT ROWS ONLY"),
        ("oracle", "SELECT a FROM t FETCH FIRST 5 ROWS WITH TIES"),
        ("oracle", "SELECT a FROM t OFFSET 5 ROWS FETCH NEXT 3 ROWS ONLY"),
    ],
)
def test_unsafe_own_limit_is_rejected_instead_of_guessed(
    db_type: str, sql: str
) -> None:
    with pytest.raises(RowLimitError) as info:
        get_adapter(db_type, "19c").apply_row_limit(sql, 100)

    assert HANGUL.search(info.value.message)


def test_input_is_not_mutated_or_commented() -> None:
    sql = "SELECT a /* c */ FROM t -- tail"

    result = get_adapter("postgresql", "14").apply_row_limit(sql, 10)

    assert "c */" not in result
    assert "tail" not in result
    assert sql == "SELECT a /* c */ FROM t -- tail"
