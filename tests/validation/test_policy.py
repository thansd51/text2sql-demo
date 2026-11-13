import re

import pytest
from sqlglot import exp

from tests.validation.corpus import (
    ATTACKS,
    NORMAL_FINAL,
    NORMAL_FIRST,
    SEMICOLON_IN_STRING,
)
from text2sql.validation import Stage, ViolationCode, validate_sql

VIEWS = {"v_object", "v_item"}
COLUMNS = {
    "v_object": ["id", "biz_code", "type_id", "obj_name", "valid_from", "valid_to"],
    "v_item": ["item_id", "object_id"],
}
PHYSICAL_TABLES = {"t", "s"}
HANGUL = re.compile(r"[가-힣]")

CREATE_STATEMENTS = [
    ("postgres", "CREATE VIEW v AS SELECT a FROM t"),
    ("oracle", "CREATE VIEW v AS SELECT a FROM t"),
    ("mysql", "CREATE VIEW v AS SELECT a FROM t"),
    ("postgres", "CREATE OR REPLACE VIEW s.v AS SELECT a FROM t"),
    ("oracle", "CREATE OR REPLACE VIEW s.v AS SELECT a FROM t"),
    ("postgres", "CREATE TABLE x (a INT)"),
    ("oracle", "CREATE TABLE x AS SELECT * FROM t"),
    ("postgres", "CREATE INDEX i ON t (a)"),
]


@pytest.mark.parametrize(("dialect", "sql"), ATTACKS)
@pytest.mark.parametrize("stage", list(Stage))
def test_attacks_are_rejected(stage: Stage, dialect: str, sql: str) -> None:
    tables = VIEWS if stage is Stage.FIRST else PHYSICAL_TABLES
    result = validate_sql(
        sql, stage=stage, dialect=dialect, allowed_tables=tables | {"t", "s"}
    )
    assert not result.ok, sql
    assert result.sql is None


@pytest.mark.parametrize(("dialect", "sql"), ATTACKS)
def test_violation_messages_are_korean(dialect: str, sql: str) -> None:
    result = validate_sql(
        sql, stage=Stage.FINAL, dialect=dialect, allowed_tables={"t", "s"}
    )
    assert result.violations
    for violation in result.violations:
        assert isinstance(violation.code, ViolationCode)
        assert re.fullmatch(r"[A-Z_]+", violation.code.value)
        assert HANGUL.search(violation.message), violation.message


@pytest.mark.parametrize(("dialect", "sql"), CREATE_STATEMENTS)
@pytest.mark.parametrize("stage", list(Stage))
def test_every_create_is_rejected_with_create_code(
    stage: Stage, dialect: str, sql: str
) -> None:
    result = validate_sql(
        sql, stage=stage, dialect=dialect, allowed_tables={"t", "s", "x", "v"}
    )
    assert not result.ok
    assert result.sql is None
    assert ViolationCode.CREATE_NOT_ALLOWED in {v.code for v in result.violations}


def test_plain_create_view_reports_only_create_code() -> None:
    result = validate_sql(
        "CREATE VIEW v AS SELECT a FROM t",
        stage=Stage.FINAL,
        dialect="postgres",
        allowed_tables={"t"},
    )
    assert [v.code for v in result.violations] == [ViolationCode.CREATE_NOT_ALLOWED]


@pytest.mark.parametrize("sql", NORMAL_FIRST)
def test_normal_first_queries_pass(sql: str) -> None:
    result = validate_sql(
        sql,
        stage=Stage.FIRST,
        dialect="postgres",
        allowed_tables=VIEWS,
        allowed_columns=COLUMNS,
    )
    assert result.ok, result.violations
    assert result.sql is not None


@pytest.mark.parametrize(("dialect", "sql"), NORMAL_FINAL)
def test_normal_final_queries_pass(dialect: str, sql: str) -> None:
    result = validate_sql(
        sql,
        stage=Stage.FINAL,
        dialect=dialect,
        allowed_tables=PHYSICAL_TABLES,
        extra_functions=(exp.CurrentTimestamp, exp.CurrentDate),
    )
    assert result.ok, result.violations


def test_exists_is_not_a_false_positive() -> None:
    result = validate_sql(
        "SELECT id FROM v_object WHERE EXISTS (SELECT 1 FROM v_item)",
        stage=Stage.FIRST,
        dialect="postgres",
        allowed_tables=VIEWS,
    )
    assert result.ok


def test_comments_are_stripped_from_returned_sql() -> None:
    result = validate_sql(
        "SELECT id /* hi */ FROM v_object -- tail",
        stage=Stage.FIRST,
        dialect="postgres",
        allowed_tables=VIEWS,
    )
    assert result.ok
    assert result.sql is not None
    assert "hi" not in result.sql
    assert "tail" not in result.sql


def test_trailing_semicolon_is_single_statement() -> None:
    result = validate_sql(
        "SELECT id FROM v_object;",
        stage=Stage.FIRST,
        dialect="postgres",
        allowed_tables=VIEWS,
    )
    assert result.ok


def test_cte_name_is_allowed_as_table() -> None:
    result = validate_sql(
        "WITH x AS (SELECT id FROM v_object) SELECT id FROM x",
        stage=Stage.FIRST,
        dialect="postgres",
        allowed_tables=VIEWS,
    )
    assert result.ok


@pytest.mark.parametrize(("dialect", "sql"), SEMICOLON_IN_STRING)
def test_semicolon_in_string_is_one_statement(dialect: str, sql: str) -> None:
    result = validate_sql(sql, stage=Stage.FINAL, dialect=dialect, allowed_tables={"t"})
    assert result.ok, result.violations


def test_mysql_executable_comment_does_not_survive_regeneration() -> None:
    result = validate_sql(
        "SELECT 1 /*! , SLEEP(5) */ FROM t",
        stage=Stage.FINAL,
        dialect="mysql",
        allowed_tables={"t"},
    )
    assert result.ok
    assert result.sql is not None
    assert "SLEEP" not in result.sql


CURRENT_DATE_SQL = "SELECT a FROM t WHERE b <= TO_CHAR(CURRENT_DATE, 'YYYYMMDD')"


def test_current_date_function_is_rejected_unless_passed_as_extra() -> None:
    result = validate_sql(
        CURRENT_DATE_SQL, stage=Stage.FINAL, dialect="postgres", allowed_tables={"t"}
    )
    assert [v.code for v in result.violations] == [ViolationCode.FUNCTION_NOT_ALLOWED]


def test_extra_functions_are_allowed_at_final_stage() -> None:
    result = validate_sql(
        CURRENT_DATE_SQL,
        stage=Stage.FINAL,
        dialect="postgres",
        allowed_tables={"t"},
        extra_functions=(exp.CurrentDate,),
    )
    assert result.ok, result.violations


@pytest.mark.parametrize("stage", list(Stage))
def test_extra_functions_are_allowed_at_every_stage(stage: Stage) -> None:
    # 모델도 오늘 날짜가 필요하면 어댑터가 알려 준 현재 날짜 함수를 쓸 수 있다
    result = validate_sql(
        CURRENT_DATE_SQL,
        stage=stage,
        dialect="postgres",
        allowed_tables={"t"},
        extra_functions=(exp.CurrentDate,),
    )
    assert result.ok, result.violations


def test_other_date_functions_stay_rejected_even_with_the_current_date_allowed() -> (
    None
):
    result = validate_sql(
        "SELECT a FROM t WHERE b <= TO_CHAR(ADD_MONTHS(SYSDATE, -1), 'YYYYMMDD')",
        stage=Stage.FIRST,
        dialect="oracle",
        allowed_tables={"t"},
        extra_functions=(exp.CurrentTimestamp,),
    )
    assert {v.code for v in result.violations} == {ViolationCode.FUNCTION_NOT_ALLOWED}
    assert any("ADD_MONTHS" in v.message for v in result.violations)


def _reject_empty_string(expression: exp.Expression) -> list[str]:
    return [
        "빈 문자열 비교는 허용되지 않습니다"
        for literal in expression.find_all(exp.Literal)
        if literal.is_string and literal.name == ""
    ]


def test_dialect_check_runs_at_first_stage() -> None:
    result = validate_sql(
        "SELECT a FROM t WHERE b = ''",
        stage=Stage.FIRST,
        dialect="oracle",
        allowed_tables={"t"},
        dialect_check=_reject_empty_string,
    )
    assert [v.code for v in result.violations] == [ViolationCode.DIALECT_RULE]
    assert result.violations[0].message == "빈 문자열 비교는 허용되지 않습니다"


def test_dialect_check_is_skipped_at_final_stage() -> None:
    # 서버가 삽입한 뷰 정의는 신뢰한다 (docs/design.md 검증과 방언의 경계).
    result = validate_sql(
        "SELECT a FROM t WHERE b = ''",
        stage=Stage.FINAL,
        dialect="oracle",
        allowed_tables={"t"},
        dialect_check=_reject_empty_string,
    )
    assert result.ok, result.violations


def test_dialect_check_is_optional() -> None:
    result = validate_sql(
        "SELECT a FROM t WHERE b = ''",
        stage=Stage.FIRST,
        dialect="oracle",
        allowed_tables={"t"},
    )
    assert result.ok, result.violations


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT no_such FROM v_object",
        "SELECT o.no_such FROM v_object o",
        "SELECT obj_name FROM v_object WHERE no_such = 'Y'",
        "WITH c AS (SELECT obj_name AS n FROM v_object) SELECT obj_name FROM c",
    ],
)
def test_unknown_column_is_rejected(sql: str) -> None:
    result = validate_sql(
        sql,
        stage=Stage.FIRST,
        dialect="postgres",
        allowed_tables=VIEWS,
        allowed_columns=COLUMNS,
    )
    assert [v.code for v in result.violations] == [ViolationCode.COLUMN_NOT_ALLOWED]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT obj_name FROM v_object WHERE biz_code = 'Y'",
        "SELECT * FROM v_object",
        "SELECT obj_name AS x FROM v_object ORDER BY x",
        "WITH c AS (SELECT obj_name AS n FROM v_object) SELECT n FROM c",
        (
            "SELECT o.obj_name FROM v_object o "
            "WHERE EXISTS (SELECT 1 FROM v_item i WHERE i.object_id = o.id)"
        ),
    ],
)
def test_known_columns_pass(sql: str) -> None:
    result = validate_sql(
        sql,
        stage=Stage.FIRST,
        dialect="postgres",
        allowed_tables=VIEWS,
        allowed_columns=COLUMNS,
    )
    assert result.ok, result.violations


def test_table_outside_allow_list_is_rejected_with_table_code() -> None:
    result = validate_sql(
        "SELECT a FROM other",
        stage=Stage.FINAL,
        dialect="postgres",
        allowed_tables={"t"},
    )
    assert [v.code for v in result.violations] == [ViolationCode.TABLE_NOT_ALLOWED]


# ---- 허용된 이름과 같은 CTE ----


@pytest.mark.parametrize("dialect", ["postgres", "oracle"])
def test_a_cte_named_like_an_allowed_view_is_rejected(dialect: str) -> None:
    # 서버가 뷰 정의를 같은 이름의 CTE로 넣으면 이름이 겹쳐 SQL이 깨진다
    result = validate_sql(
        "WITH v_object AS (SELECT id FROM v_object) SELECT id FROM v_object",
        stage=Stage.FIRST,
        dialect=dialect,
        allowed_tables=VIEWS,
    )

    assert [v.code for v in result.violations] == [ViolationCode.TABLE_NOT_ALLOWED]
    assert "v_object" in result.violations[0].message
    assert HANGUL.search(result.violations[0].message)


def test_a_cte_named_like_an_allowed_view_is_rejected_case_insensitively() -> None:
    result = validate_sql(
        "WITH V_OBJECT AS (SELECT 1 AS id FROM t) SELECT id FROM V_OBJECT",
        stage=Stage.FIRST,
        dialect="postgres",
        allowed_tables=VIEWS | {"t"},
    )

    assert not result.ok


def test_a_cte_with_another_name_is_still_fine() -> None:
    result = validate_sql(
        "WITH recent AS (SELECT id FROM v_object) SELECT id FROM recent",
        stage=Stage.FIRST,
        dialect="postgres",
        allowed_tables=VIEWS,
    )

    assert result.ok, result.violations


def test_the_server_inserted_view_cte_passes_the_final_check() -> None:
    # 최종 검증의 허용 목록은 물리 테이블이다. 뷰 이름의 CTE는 충돌이 아니다.
    result = validate_sql(
        "WITH v_object AS (SELECT m.id AS id FROM t m) SELECT id FROM v_object",
        stage=Stage.FINAL,
        dialect="oracle",
        allowed_tables={"t"},
    )

    assert result.ok, result.violations
