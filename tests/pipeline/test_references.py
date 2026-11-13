import pytest

from tests.fakes import FakeLLM
from tests.pipeline.conftest import BAD_TABLE, GOOD, MAX_ROWS, MetadataFactory
from text2sql.pipeline import Reference, SqlGenerator, Status, extract_references
from text2sql.semantic import ProjectMetadata

COLUMNS = {
    "OBJ_MAIN": ["SID", "BIZCODE", "TYPEID", "OBJ_NAME", "VF_DT", "VT_DT"],
    "OBJ_INV": ["INV_TYPE", "SID", "SUBSID"],
}


def refs(sql: str, dialect: str) -> list[tuple[str, tuple[str, ...]]]:
    result = extract_references(sql, dialect=dialect, columns_by_table=COLUMNS)
    return [(r.table, r.columns) for r in result]


@pytest.mark.parametrize("dialect", ["postgres", "oracle"])
@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "SELECT OBJ_NAME FROM OBJ_MAIN WHERE TYPEID = 101",
            [("OBJ_MAIN", ("TYPEID", "OBJ_NAME"))],
        ),
        # 컬럼은 테이블에 선언된 순서로 나온다 (SQL에 쓴 순서가 아니다)
        (
            "SELECT VT_DT, TYPEID, SID FROM OBJ_MAIN",
            [("OBJ_MAIN", ("SID", "TYPEID", "VT_DT"))],
        ),
        ("SELECT COUNT(*) FROM OBJ_MAIN", [("OBJ_MAIN", ())]),
        ("SELECT * FROM OBJ_INV", [("OBJ_INV", ("INV_TYPE", "SID", "SUBSID"))]),
        # 같은 이름 컬럼이 두 테이블에 있어도 별칭으로 구분한다
        (
            (
                "SELECT T3.BIZCODE, T3.OBJ_NAME FROM OBJ_MAIN T1, OBJ_INV T2, OBJ_MAIN T3 "
                "WHERE T1.BIZCODE = 'A0001' AND T1.SID = T2.SID AND T2.SUBSID = T3.SID"
            ),
            [
                ("OBJ_INV", ("SID", "SUBSID")),
                ("OBJ_MAIN", ("SID", "BIZCODE", "OBJ_NAME")),
            ],
        ),
        (
            "SELECT o.OBJ_NAME, i.INV_TYPE FROM OBJ_MAIN o JOIN OBJ_INV i ON i.SID = o.SID",
            [("OBJ_INV", ("INV_TYPE", "SID")), ("OBJ_MAIN", ("SID", "OBJ_NAME"))],
        ),
        # CTE와 파생 테이블은 테이블이 아니다. 안쪽 질의에서 실제 컬럼을 센다
        (
            "WITH c AS (SELECT OBJ_NAME AS n FROM OBJ_MAIN) SELECT n FROM c",
            [("OBJ_MAIN", ("OBJ_NAME",))],
        ),
        (
            "SELECT n FROM (SELECT OBJ_NAME AS n FROM OBJ_MAIN) s",
            [("OBJ_MAIN", ("OBJ_NAME",))],
        ),
        # 하위 질의와 상관 하위 질의
        (
            "SELECT o.OBJ_NAME FROM OBJ_MAIN o WHERE o.SID IN (SELECT SUBSID FROM OBJ_INV)",
            [("OBJ_INV", ("SUBSID",)), ("OBJ_MAIN", ("SID", "OBJ_NAME"))],
        ),
        (
            (
                "SELECT o.OBJ_NAME FROM OBJ_MAIN o WHERE EXISTS "
                "(SELECT 1 FROM OBJ_INV i WHERE i.SID = o.SID AND i.INV_TYPE = 1)"
            ),
            [("OBJ_INV", ("INV_TYPE", "SID")), ("OBJ_MAIN", ("SID", "OBJ_NAME"))],
        ),
        (
            "SELECT OBJ_NAME FROM OBJ_MAIN UNION SELECT BIZCODE FROM OBJ_MAIN",
            [("OBJ_MAIN", ("BIZCODE", "OBJ_NAME"))],
        ),
        # 선택 항목의 별칭은 컬럼이 아니다
        (
            "SELECT OBJ_NAME AS x FROM OBJ_MAIN ORDER BY x",
            [("OBJ_MAIN", ("OBJ_NAME",))],
        ),
    ],
)
def test_references_for_common_shapes(
    dialect: str, sql: str, expected: list[tuple[str, tuple[str, ...]]]
) -> None:
    assert refs(sql, dialect) == expected


def test_case_of_the_written_sql_does_not_matter() -> None:
    assert refs("select obj_name from obj_main", "oracle") == [
        ("OBJ_MAIN", ("OBJ_NAME",))
    ]
    assert refs("SELECT Obj_Name FROM Obj_Main", "postgres") == [
        ("OBJ_MAIN", ("OBJ_NAME",))
    ]


def test_quoted_identifiers_that_pass_validation_do_not_crash() -> None:
    # Oracle에서 따옴표 친 대문자는 따옴표 없는 이름과 같다 (1차 검증도 통과한다)
    assert refs('SELECT "OBJ_NAME" FROM "OBJ_MAIN"', "oracle") == [
        ("OBJ_MAIN", ("OBJ_NAME",))
    ]
    assert refs('SELECT "obj_name" FROM "obj_main"', "postgres") == [
        ("OBJ_MAIN", ("OBJ_NAME",))
    ]


def test_oracle_row_limit_syntax_is_understood() -> None:
    sql = "SELECT OBJ_NAME FROM OBJ_MAIN FETCH FIRST 3 ROWS ONLY"

    assert refs(sql, "oracle") == [("OBJ_MAIN", ("OBJ_NAME",))]


def test_result_type_is_a_frozen_reference() -> None:
    result = extract_references(
        "SELECT SID FROM OBJ_MAIN", dialect="postgres", columns_by_table=COLUMNS
    )

    assert result == (Reference(table="OBJ_MAIN", columns=("SID",)),)


# ---- 파이프라인 결과에 실린다 ----


def test_generation_result_carries_the_references(metadata: ProjectMetadata) -> None:
    result = SqlGenerator(FakeLLM(GOOD), 2, max_rows=MAX_ROWS).run("질문", metadata)

    assert result.status is Status.OK
    assert result.references == (Reference("OBJ_MAIN", ("SID", "OBJ_NAME")),)


def test_references_describe_the_models_query_not_the_limit_wrapper(
    metadata: ProjectMetadata,
) -> None:
    result = SqlGenerator(FakeLLM(GOOD), 2, max_rows=MAX_ROWS).run("질문", metadata)

    assert result.sql is not None and "ROWNUM" in result.sql
    assert [r.table for r in result.references] == [
        "OBJ_MAIN"
    ]  # ROWNUM은 컬럼이 아니다


def test_rejected_result_has_no_references(make_metadata: MetadataFactory) -> None:
    result = SqlGenerator(FakeLLM(BAD_TABLE), 0, max_rows=MAX_ROWS).run(
        "질문", make_metadata()
    )

    assert result.status is Status.REJECTED
    assert result.references == ()


@pytest.mark.parametrize(
    ("db_type", "db_version"),
    [("oracle", "11g"), ("oracle", "19c"), ("postgresql", "14")],
)
def test_references_work_for_every_supported_database(
    make_metadata: MetadataFactory, db_type: str, db_version: str
) -> None:
    metadata = make_metadata(db_type, db_version)
    llm = FakeLLM("SELECT o.OBJ_NAME FROM OBJ_MAIN o WHERE o.SID = 1")

    result = SqlGenerator(llm, 0, max_rows=MAX_ROWS).run("질문", metadata)

    assert result.references == (Reference("OBJ_MAIN", ("SID", "OBJ_NAME")),)
