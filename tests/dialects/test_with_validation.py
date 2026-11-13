"""어댑터 결과가 validation과 맞물리는지 확인한다.

src에서는 dialects와 validation이 서로 import하지 않는다. 연결은 pipeline의 몫이고,
여기서는 그 연결을 흉내 내어 둘이 맞물리는지만 본다.
"""

import pytest

from text2sql.dialects import get_adapter
from text2sql.validation import Stage, ViolationCode, validate_sql

TABLES = {"obj_main", "obj_inv"}
TODAY_ORACLE = (
    "SELECT BIZCODE FROM OBJ_MAIN WHERE VF_DT <= TO_CHAR(SYSDATE, 'YYYYMMDD')"
)
TODAY_POSTGRES = (
    "SELECT BIZCODE FROM OBJ_MAIN WHERE VF_DT <= TO_CHAR(CURRENT_DATE, 'YYYYMMDD')"
)


def check(db_type: str, version: str, sql: str, stage: Stage):
    adapter = get_adapter(db_type, version)
    return validate_sql(
        sql,
        stage=stage,
        dialect=adapter.sqlglot_dialect,
        allowed_tables=TABLES,
        extra_functions=adapter.extra_functions,
        dialect_check=adapter.check if stage is Stage.FIRST else None,
    )


@pytest.mark.parametrize("stage", list(Stage))
@pytest.mark.parametrize(
    ("db_type", "sql"),
    [("oracle", TODAY_ORACLE), ("postgresql", TODAY_POSTGRES)],
)
def test_the_adapters_current_date_function_is_allowed(
    db_type: str, sql: str, stage: Stage
) -> None:
    result = check(db_type, "19c" if db_type == "oracle" else "14", sql, stage)

    assert result.ok, result.violations


def test_oracle_sysdate_and_postgresql_current_date_survive_regeneration() -> None:
    oracle = check("oracle", "19c", TODAY_ORACLE, Stage.FIRST)
    postgres = check("postgresql", "14", TODAY_POSTGRES, Stage.FIRST)

    assert oracle.sql is not None and "SYSDATE" in oracle.sql
    assert postgres.sql is not None and "CURRENT_DATE" in postgres.sql


def test_oracle_rejects_the_postgresql_current_date_function() -> None:
    result = check("oracle", "19c", TODAY_POSTGRES, Stage.FIRST)

    assert ViolationCode.FUNCTION_NOT_ALLOWED in {v.code for v in result.violations}
    assert "CURRENT_DATE" in result.violations[0].message


def test_postgresql_rejects_the_oracle_current_date_function() -> None:
    # PostgreSQL 방언에서 SYSDATE는 함수가 아니라 컬럼으로 읽힌다. 실제 파이프라인처럼
    # 컬럼 목록을 함께 넘기면 알 수 없는 컬럼으로 거부된다.
    adapter = get_adapter("postgresql", "14")

    result = validate_sql(
        TODAY_ORACLE,
        stage=Stage.FIRST,
        dialect=adapter.sqlglot_dialect,
        allowed_tables=TABLES,
        allowed_columns={"OBJ_MAIN": ["BIZCODE", "VF_DT"]},
        extra_functions=adapter.extra_functions,
    )

    assert [v.code for v in result.violations] == [ViolationCode.COLUMN_NOT_ALLOWED]


@pytest.mark.parametrize("db_type", ["oracle", "postgresql"])
@pytest.mark.parametrize(
    "query",
    [
        "SELECT BIZCODE FROM OBJ_MAIN ORDER BY BIZCODE",
        "SELECT BIZCODE FROM OBJ_MAIN FETCH FIRST 5 ROWS ONLY",
        "SELECT BIZCODE FROM OBJ_MAIN UNION SELECT BIZCODE FROM OBJ_MAIN",
        "WITH c AS (SELECT BIZCODE FROM OBJ_MAIN) SELECT BIZCODE FROM c",
    ],
)
def test_row_limited_sql_passes_final_validation(db_type: str, query: str) -> None:
    adapter = get_adapter(db_type, "19c")

    limited = adapter.apply_row_limit(query, 100)
    result = check(db_type, "19c", limited, Stage.FINAL)

    assert result.ok, (limited, result.violations)


def test_oracle_own_fetch_first_would_fail_final_validation_without_the_rewrite() -> (
    None
):
    # 안쪽에 FETCH를 남기면 "행 제한은 최상위 질의에만" 규칙에 걸린다. 어댑터가 이를 피한다.
    inner_fetch = "SELECT * FROM (SELECT BIZCODE FROM OBJ_MAIN FETCH FIRST 5 ROWS ONLY) WHERE ROWNUM <= 100"
    result = check("oracle", "19c", inner_fetch, Stage.FINAL)
    assert ViolationCode.QUERY_SHAPE_NOT_ALLOWED in {v.code for v in result.violations}

    adapter = get_adapter("oracle", "19c")
    rewritten = adapter.apply_row_limit(
        "SELECT BIZCODE FROM OBJ_MAIN FETCH FIRST 5 ROWS ONLY", 100
    )
    assert check("oracle", "19c", rewritten, Stage.FINAL).ok


@pytest.mark.parametrize(
    ("db_type", "version"),
    [("oracle", "11g"), ("oracle", "19c"), ("postgresql", "14")],
)
def test_adapter_check_plugs_into_first_stage_validation(
    db_type: str, version: str
) -> None:
    result = check(
        db_type,
        version,
        "SELECT BIZCODE FROM OBJ_MAIN FETCH FIRST 3 ROWS ONLY",
        Stage.FIRST,
    )

    codes = {v.code for v in result.violations}
    if (db_type, version) == ("oracle", "11g"):
        assert ViolationCode.DIALECT_RULE in codes
    else:
        assert ViolationCode.DIALECT_RULE not in codes
