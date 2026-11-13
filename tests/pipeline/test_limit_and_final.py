"""설계서 5~6단계: 행 제한 강제와 최종 검증. 그리고 공통 예시 검사(check_example)."""

import re

import pytest
import sqlglot
from sqlglot import exp

from tests.fakes import FakeLLM
from tests.pipeline.conftest import GOOD, MAX_ROWS, MetadataFactory
from text2sql.dialects import get_adapter
from text2sql.pipeline import (
    FinalValidationError,
    GenerationResult,
    SqlGenerator,
    Status,
    check_example,
    finish_sql,
)
from text2sql.semantic import ProjectMetadata

HANGUL = re.compile(r"[가-힣]")


def generate(
    metadata: ProjectMetadata, *replies: str, retries: int = 2, max_rows: int = MAX_ROWS
) -> GenerationResult:
    return SqlGenerator(FakeLLM(*replies), retries, max_rows=max_rows).run(
        "질문", metadata
    )


def tables_in(sql: str, dialect: str) -> set[str]:
    tree = sqlglot.parse_one(sql, read=dialect)
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    return {t.name for t in tree.find_all(exp.Table) if t.name.lower() not in ctes}


# ---- 행 제한 ----


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("SELECT OBJ_NAME FROM OBJ_MAIN", 100),  # 질의에 제한이 없으면 서버 상한
        ("SELECT OBJ_NAME FROM OBJ_MAIN FETCH FIRST 5 ROWS ONLY", 5),  # 더 작으면 그 값
        (
            "SELECT OBJ_NAME FROM OBJ_MAIN FETCH FIRST 5000 ROWS ONLY",
            100,
        ),  # 더 크면 상한
    ],
)
def test_oracle_row_limit_is_the_smaller_of_the_query_and_the_server(
    make_metadata: MetadataFactory, reply: str, expected: int
) -> None:
    result = generate(make_metadata(), reply)

    assert result.sql is not None
    assert result.sql.endswith(f"WHERE ROWNUM <= {expected}")
    assert "FETCH" not in result.sql


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("SELECT OBJ_NAME FROM OBJ_MAIN", "LIMIT 100"),
        ("SELECT OBJ_NAME FROM OBJ_MAIN LIMIT 5", "LIMIT 5"),
        ("SELECT OBJ_NAME FROM OBJ_MAIN LIMIT 5000", "LIMIT 100"),
        ("SELECT OBJ_NAME FROM OBJ_MAIN LIMIT 5 OFFSET 2", "LIMIT 5 OFFSET 2"),
    ],
)
def test_postgresql_row_limit(
    make_metadata: MetadataFactory, reply: str, expected: str
) -> None:
    result = generate(make_metadata("postgresql", "14"), reply)

    assert result.sql is not None
    assert result.sql.endswith(expected)


def test_the_server_row_limit_comes_from_the_setting(metadata: ProjectMetadata) -> None:
    result = generate(metadata, GOOD, max_rows=7)

    assert result.sql is not None
    assert result.sql.endswith("WHERE ROWNUM <= 7")


def test_oracle_wraps_a_query_with_its_own_cte_and_keeps_the_with_clause_outside(
    metadata: ProjectMetadata,
) -> None:
    sql = "WITH c AS (SELECT OBJ_NAME FROM OBJ_MAIN) SELECT OBJ_NAME FROM c ORDER BY OBJ_NAME"

    result = generate(metadata, sql)

    assert result.sql == (
        "WITH c AS (SELECT OBJ_NAME FROM OBJ_MAIN) "
        "SELECT * FROM (SELECT OBJ_NAME FROM c ORDER BY OBJ_NAME) WHERE ROWNUM <= 100"
    )


def test_union_is_limited_as_a_whole(make_metadata: MetadataFactory) -> None:
    sql = "SELECT OBJ_NAME FROM OBJ_MAIN UNION SELECT BIZCODE FROM OBJ_MAIN"

    postgres = generate(make_metadata("postgresql", "14"), sql)
    oracle = generate(make_metadata("oracle", "19c"), sql)

    assert postgres.sql is not None and postgres.sql.endswith("LIMIT 100")
    assert oracle.sql is not None and oracle.sql.startswith(
        "SELECT * FROM (SELECT OBJ_NAME"
    )


@pytest.mark.parametrize(
    ("db_type", "reply"),
    [
        ("oracle", "SELECT OBJ_NAME FROM OBJ_MAIN FETCH FIRST 5 PERCENT ROWS ONLY"),
        (
            "oracle",
            "SELECT OBJ_NAME FROM OBJ_MAIN ORDER BY OBJ_NAME FETCH FIRST 3 ROWS WITH TIES",
        ),
        ("postgresql", "SELECT OBJ_NAME FROM OBJ_MAIN LIMIT SID"),
    ],
)
def test_a_row_limit_the_server_cannot_handle_is_sent_back_for_a_rewrite(
    make_metadata: MetadataFactory, db_type: str, reply: str
) -> None:
    version = "19c" if db_type == "oracle" else "14"
    llm = FakeLLM(reply, GOOD)

    result = SqlGenerator(llm, 2, max_rows=MAX_ROWS).run(
        "질문", make_metadata(db_type, version)
    )

    assert result.status is Status.OK
    assert result.attempts == 2
    retry_message = llm.prompts[1][1].content
    assert "ROW_LIMIT_ERROR" in retry_message
    assert HANGUL.search(retry_message.split("오류:")[1])


def test_an_unhandleable_row_limit_every_time_ends_in_a_rejection(
    metadata: ProjectMetadata,
) -> None:
    bad = "SELECT OBJ_NAME FROM OBJ_MAIN FETCH FIRST 5 PERCENT ROWS ONLY"

    result = generate(metadata, bad, bad, bad)

    assert result.status is Status.REJECTED
    assert result.sql is None
    assert result.reason is not None
    assert result.reason.code == "SQL_VALIDATION_FAILED"


# ---- 모델이 허용 테이블과 같은 이름의 CTE를 쓰는 경우 ----


def test_a_cte_named_like_a_table_is_sent_back(metadata: ProjectMetadata) -> None:
    clash = "WITH OBJ_MAIN AS (SELECT SID FROM OBJ_MAIN) SELECT SID FROM OBJ_MAIN"
    llm = FakeLLM(clash, GOOD)

    result = SqlGenerator(llm, 2, max_rows=MAX_ROWS).run("질문", metadata)

    assert result.status is Status.OK
    assert result.attempts == 2
    assert "CTE 이름이 허용된 뷰/테이블 이름과 같습니다" in llm.prompts[1][1].content


# ---- 최종 검증 ----


@pytest.mark.parametrize(
    ("db_type", "version"), [("oracle", "19c"), ("oracle", "11g"), ("postgresql", "14")]
)
def test_final_sql_uses_only_the_profiles_tables(
    make_metadata: MetadataFactory, db_type: str, version: str
) -> None:
    sql = "SELECT T3.OBJ_NAME FROM OBJ_MAIN T1, OBJ_INV T2, OBJ_MAIN T3 WHERE T1.SID = T2.SID AND T2.SUBSID = T3.SID"

    result = generate(make_metadata(db_type, version), sql)

    assert result.status is Status.OK
    assert result.sql is not None
    dialect = get_adapter(db_type, version).sqlglot_dialect
    assert tables_in(result.sql, dialect) == {"OBJ_MAIN", "OBJ_INV"}


def test_final_validation_failure_is_a_server_error_with_codes_only(
    metadata: ProjectMetadata,
) -> None:
    class BrokenLimit:
        """행 제한 단계가 잘못된 SQL을 만든 서버 쪽 결함을 흉내 낸다."""

        sqlglot_dialect = "oracle"
        extra_functions = ()

        def apply_row_limit(self, sql: str, max_rows: int) -> str:
            return "DELETE FROM OBJ_MAIN"

    with pytest.raises(FinalValidationError) as info:
        finish_sql(GOOD, metadata, BrokenLimit(), 100)  # type: ignore[arg-type]

    assert info.value.code == "FINAL_VALIDATION_FAILED"
    assert "STATEMENT_NOT_ALLOWED" in info.value.message
    assert HANGUL.search(info.value.message)
    assert "DELETE" not in info.value.message  # SQL 내용은 담지 않는다


def test_finish_sql_applies_the_limit_and_validates(metadata: ProjectMetadata) -> None:
    adapter = get_adapter("oracle", "19c")

    assert finish_sql(GOOD, metadata, adapter, 50) == (
        "SELECT * FROM (SELECT OBJ_NAME FROM OBJ_MAIN WHERE SID = 1) WHERE ROWNUM <= 50"
    )


# ---- 공통 예시 검사 (시작할 때 모든 프로젝트의 DB에서 확인한다) ----


def test_a_good_example_passes_for_every_database(
    make_metadata: MetadataFactory,
) -> None:
    for db_type, version in (
        ("oracle", "11g"),
        ("oracle", "19c"),
        ("postgresql", "14"),
    ):
        metadata = make_metadata(db_type, version)
        adapter = get_adapter(db_type, version)

        assert check_example(GOOD, metadata, adapter) == [], (db_type, version)


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT NO_SUCH FROM OBJ_MAIN", "COLUMN_NOT_ALLOWED"),
        ("SELECT SID FROM OBJ_DETAIL", "TABLE_NOT_ALLOWED"),
        ("DELETE FROM OBJ_MAIN", "STATEMENT_NOT_ALLOWED"),
        ("SELECT SID FROM OBJ_MAIN FETCH FIRST 5 PERCENT ROWS ONLY", "행 제한"),
    ],
)
def test_a_bad_example_is_reported_in_korean(
    metadata: ProjectMetadata, sql: str, code: str
) -> None:
    reasons = check_example(sql, metadata, get_adapter("oracle", "19c"))

    assert reasons
    assert any(code in reason for reason in reasons)
    assert all(HANGUL.search(reason) for reason in reasons)


def test_an_example_can_be_fine_for_one_database_and_wrong_for_another(
    make_metadata: MetadataFactory,
) -> None:
    sql = "SELECT SID FROM OBJ_MAIN WHERE OBJ_NAME = ''"

    postgres = check_example(
        sql, make_metadata("postgresql", "14"), get_adapter("postgresql", "14")
    )
    oracle = check_example(
        sql, make_metadata("oracle", "19c"), get_adapter("oracle", "19c")
    )
    old_oracle_fetch = check_example(
        "SELECT SID FROM OBJ_MAIN FETCH FIRST 3 ROWS ONLY",
        make_metadata("oracle", "11g"),
        get_adapter("oracle", "11g"),
    )

    assert postgres == []
    assert oracle and "DIALECT_RULE" in oracle[0]
    assert old_oracle_fetch and "FETCH FIRST" in old_oracle_fetch[0]
