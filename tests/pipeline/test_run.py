import logging
import re

import pytest

from tests.fakes import FakeLLM
from tests.pipeline.conftest import (
    BAD_COLUMN,
    BAD_TABLE,
    GOOD,
    MAX_ROWS,
    MetadataFactory,
)
from text2sql.dialects import UnsupportedDbTypeError
from text2sql.llm import LLMTimeoutError, LLMUnavailableError
from text2sql.pipeline import (
    REASON_OUT_OF_SCOPE,
    REASON_VALIDATION_FAILED,
    GenerationResult,
    SqlGenerator,
    Status,
    extract_sql,
)
from text2sql.semantic import ProjectMetadata

HANGUL = re.compile(r"[가-힣]")

# 시험용 Oracle 19c 프로젝트에서 GOOD이 최종 SQL이 되면 이 모양이다 (행 제한 100)
FINAL_GOOD = (
    "SELECT * FROM (SELECT OBJ_NAME FROM OBJ_MAIN WHERE SID = 1) WHERE ROWNUM <= 100"
)


def run(
    llm: FakeLLM, metadata: ProjectMetadata, *, retries: int = 2, question: str = "질문"
) -> GenerationResult:
    return SqlGenerator(llm, max_repair_attempts=retries, max_rows=MAX_ROWS).run(
        question, metadata
    )


# ---- 성공 ----


def test_success_on_the_first_attempt(metadata: ProjectMetadata) -> None:
    llm = FakeLLM(GOOD)

    result = run(llm, metadata)

    assert result.status is Status.OK
    assert result.sql == FINAL_GOOD
    assert result.attempts == 1
    assert result.reason is None
    assert len(llm.prompts) == 1


def test_first_prompt_has_the_schema_and_the_question(
    metadata: ProjectMetadata,
) -> None:
    llm = FakeLLM(GOOD)

    run(llm, metadata, question="상품 이름을 알려줘")

    system, user = llm.prompts[0]
    assert "OBJ_MAIN" in system.content
    assert "OBJ_NAME" in system.content
    assert user.content == "질문: 상품 이름을 알려줘"


@pytest.mark.parametrize(
    "reply",
    [
        f"```sql\n{GOOD}\n```",
        f"```\n{GOOD}\n```",
        f"  \n{GOOD};\n",
        f"{GOOD} /* 설명 */ -- 끝",
    ],
)
def test_code_fences_comments_and_semicolons_are_cleaned(
    metadata: ProjectMetadata, reply: str
) -> None:
    result = run(FakeLLM(reply), metadata)

    assert result.status is Status.OK
    assert result.sql == FINAL_GOOD


def test_returned_sql_is_regenerated_from_the_ast(metadata: ProjectMetadata) -> None:
    result = run(FakeLLM("select   OBJ_NAME   from   OBJ_MAIN"), metadata)

    assert (
        result.sql
        == "SELECT * FROM (SELECT OBJ_NAME FROM OBJ_MAIN) WHERE ROWNUM <= 100"
    )


def test_the_models_table_and_column_names_are_what_the_answer_uses(
    metadata: ProjectMetadata,
) -> None:
    # 뷰로 바꿔 쓰지 않는다. 모델이 쓴 실제 테이블과 컬럼이 그대로 최종 SQL에 있다.
    result = run(
        FakeLLM("SELECT BIZCODE, OBJ_NAME FROM OBJ_MAIN WHERE TYPEID = 101"), metadata
    )

    assert result.sql is not None
    assert "FROM OBJ_MAIN WHERE TYPEID = 101" in result.sql
    assert "WITH" not in result.sql


# ---- 재시도 후 성공 ----


def test_success_after_one_retry(metadata: ProjectMetadata) -> None:
    llm = FakeLLM(BAD_COLUMN, GOOD)

    result = run(llm, metadata)

    assert result.status is Status.OK
    assert result.sql == FINAL_GOOD
    assert result.attempts == 2
    assert len(llm.prompts) == 2


def test_retry_prompt_carries_the_previous_sql_and_the_error(
    metadata: ProjectMetadata,
) -> None:
    llm = FakeLLM(BAD_COLUMN, GOOD)

    run(llm, metadata, question="상품 이름")

    first_user = llm.prompts[0][1].content
    retry_user = llm.prompts[1][1].content
    assert "이전 답변" not in first_user
    assert retry_user.startswith("질문: 상품 이름")
    assert f"이전 답변: {BAD_COLUMN}" in retry_user
    assert "COLUMN_NOT_ALLOWED" in retry_user
    assert HANGUL.search(retry_user.split("오류:")[1])
    assert llm.prompts[0][0] == llm.prompts[1][0]  # 시스템 프롬프트는 그대로다


def test_success_on_the_last_allowed_attempt(metadata: ProjectMetadata) -> None:
    llm = FakeLLM(BAD_COLUMN, BAD_TABLE, GOOD)

    result = run(llm, metadata, retries=2)

    assert result.status is Status.OK
    assert result.attempts == 3
    assert len(llm.prompts) == 3
    # 3번째 요청에는 바로 앞 답변과 그 오류가 들어간다
    assert f"이전 답변: {BAD_TABLE}" in llm.prompts[2][1].content
    assert "TABLE_NOT_ALLOWED" in llm.prompts[2][1].content


# ---- 재시도 초과 거부 ----


def test_rejected_after_exhausting_retries(metadata: ProjectMetadata) -> None:
    llm = FakeLLM(BAD_COLUMN, BAD_TABLE, BAD_COLUMN)

    result = run(llm, metadata, retries=2)

    assert result.status is Status.REJECTED
    assert result.sql is None
    assert result.attempts == 3
    assert result.reason is not None
    assert result.reason.code == REASON_VALIDATION_FAILED
    assert HANGUL.search(result.reason.message)
    assert len(llm.prompts) == 3  # 1회 + 재시도 2회, 그 이상 호출하지 않는다


def test_rejection_does_not_leak_the_rejected_sql(metadata: ProjectMetadata) -> None:
    result = run(FakeLLM(BAD_TABLE, BAD_TABLE, BAD_TABLE), metadata)

    assert result.sql is None
    assert result.reason is not None
    assert "OBJ_DETAIL" not in result.reason.message


@pytest.mark.parametrize("retries", [0, 1, 2, 5])
def test_number_of_llm_calls_is_one_plus_retries(
    metadata: ProjectMetadata, retries: int
) -> None:
    llm = FakeLLM(*[BAD_COLUMN] * (retries + 1))

    result = run(llm, metadata, retries=retries)

    assert result.status is Status.REJECTED
    assert len(llm.prompts) == retries + 1
    assert result.attempts == retries + 1


def test_zero_retries_means_a_single_call_and_no_second_chance(
    metadata: ProjectMetadata,
) -> None:
    llm = FakeLLM(BAD_COLUMN, GOOD)

    result = run(llm, metadata, retries=0)

    assert result.status is Status.REJECTED
    assert len(llm.prompts) == 1
    assert llm.replies == [GOOD]  # 두 번째 답변은 쓰이지 않았다


def test_negative_retries_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="재시도 횟수"):
        SqlGenerator(FakeLLM(), max_repair_attempts=-1, max_rows=MAX_ROWS)


@pytest.mark.parametrize("max_rows", [0, -1])
def test_the_row_limit_setting_must_be_positive(max_rows: int) -> None:
    with pytest.raises(ValueError, match="최대 행 수"):
        SqlGenerator(FakeLLM(), 2, max_rows=max_rows)


# ---- 검증 규칙이 실제로 걸리는지 ----


@pytest.mark.parametrize(
    ("bad_sql", "code"),
    [
        (BAD_COLUMN, "COLUMN_NOT_ALLOWED"),
        (BAD_TABLE, "TABLE_NOT_ALLOWED"),
        ("SELECT * FROM DUAL", "TABLE_NOT_ALLOWED"),
        ("DELETE FROM OBJ_MAIN", "STATEMENT_NOT_ALLOWED"),
        ("CREATE VIEW v AS SELECT SID FROM OBJ_MAIN", "CREATE_NOT_ALLOWED"),
        ("CREATE OR REPLACE VIEW v AS SELECT SID FROM OBJ_MAIN", "CREATE_NOT_ALLOWED"),
        ("SELECT SID FROM OBJ_MAIN; DROP TABLE OBJ_MAIN", "MULTIPLE_STATEMENTS"),
        ("SELEC FROM", "PARSE_ERROR"),
        ("", "MULTIPLE_STATEMENTS"),
        ("SELECT SID FROM OBJ_MAIN FOR UPDATE", "FORBIDDEN_CLAUSE"),
        ("SELECT ADD_MONTHS(SYSDATE, 1) FROM OBJ_MAIN", "FUNCTION_NOT_ALLOWED"),
        ("SELECT SID FROM SYS.OBJ_MAIN", "TABLE_NOT_ALLOWED"),
    ],
)
def test_each_kind_of_bad_sql_is_sent_back_with_its_error_code(
    metadata: ProjectMetadata, bad_sql: str, code: str
) -> None:
    llm = FakeLLM(bad_sql, GOOD)

    result = run(llm, metadata)

    assert result.status is Status.OK
    assert result.attempts == 2
    assert code in llm.prompts[1][1].content


def test_create_view_is_never_accepted(metadata: ProjectMetadata) -> None:
    sql = "CREATE VIEW v AS SELECT SID FROM OBJ_MAIN"

    result = run(FakeLLM(sql, sql, sql), metadata)

    assert result.status is Status.REJECTED
    assert result.sql is None


def test_oracle_rules_are_applied_to_the_first_check(
    make_metadata: MetadataFactory,
) -> None:
    empty_compare = "SELECT SID FROM OBJ_MAIN WHERE OBJ_NAME = ''"
    llm = FakeLLM(empty_compare, GOOD)

    result = run(llm, make_metadata("oracle", "19c"))

    assert result.status is Status.OK
    assert "DIALECT_RULE" in llm.prompts[1][1].content
    assert "빈 문자열" in llm.prompts[1][1].content


def test_the_same_sql_is_fine_for_postgresql(make_metadata: MetadataFactory) -> None:
    result = run(
        FakeLLM("SELECT SID FROM OBJ_MAIN WHERE OBJ_NAME = ''"),
        make_metadata("postgresql", "14"),
    )

    assert result.status is Status.OK


@pytest.mark.parametrize(
    ("db_version", "accepted"), [("11g", False), ("12c", True), ("19c", True)]
)
def test_fetch_first_depends_on_the_oracle_version(
    make_metadata: MetadataFactory, db_version: str, accepted: bool
) -> None:
    fetch = "SELECT SID FROM OBJ_MAIN FETCH FIRST 3 ROWS ONLY"

    result = run(FakeLLM(fetch), make_metadata("oracle", db_version), retries=0)

    assert (result.status is Status.OK) is accepted


# ---- 현재 날짜: 모델이 어댑터가 알려 준 함수를 쓸 수 있다 ----


def test_oracle_model_may_use_sysdate(make_metadata: MetadataFactory) -> None:
    sql = "SELECT COUNT(*) FROM OBJ_MAIN WHERE OBJ_NAME <= TO_CHAR(SYSDATE, 'YYYYMMDD')"

    result = run(FakeLLM(sql), make_metadata("oracle", "19c"), retries=0)

    assert result.status is Status.OK
    assert result.sql is not None and "SYSDATE" in result.sql


def test_postgresql_model_may_use_current_date(make_metadata: MetadataFactory) -> None:
    sql = "SELECT COUNT(*) FROM OBJ_MAIN WHERE OBJ_NAME <= TO_CHAR(CURRENT_DATE, 'YYYYMMDD')"

    result = run(FakeLLM(sql), make_metadata("postgresql", "14"), retries=0)

    assert result.status is Status.OK
    assert result.sql is not None and "CURRENT_DATE" in result.sql


def test_the_other_databases_date_function_is_sent_back(
    make_metadata: MetadataFactory,
) -> None:
    wrong = "SELECT COUNT(*) FROM OBJ_MAIN WHERE OBJ_NAME <= TO_CHAR(CURRENT_DATE, 'YYYYMMDD')"
    right = (
        "SELECT COUNT(*) FROM OBJ_MAIN WHERE OBJ_NAME <= TO_CHAR(SYSDATE, 'YYYYMMDD')"
    )
    llm = FakeLLM(wrong, right)

    result = run(llm, make_metadata("oracle", "19c"))

    assert result.status is Status.OK
    assert "FUNCTION_NOT_ALLOWED" in llm.prompts[1][1].content


def test_other_date_calculation_functions_are_still_rejected(
    make_metadata: MetadataFactory,
) -> None:
    sql = "SELECT SID FROM OBJ_MAIN WHERE OBJ_NAME <= TO_CHAR(ADD_MONTHS(SYSDATE, -1), 'YYYYMMDD')"

    result = run(FakeLLM(sql), make_metadata("oracle", "19c"), retries=0)

    assert result.status is Status.REJECTED


# ---- 질문이 스키마 밖일 때 ----


@pytest.mark.parametrize(
    "reply", ["UNSUPPORTED", "unsupported", " UNSUPPORTED. ", "UNSUPPORTED;"]
)
def test_unsupported_answer_is_rejected_without_retry(
    metadata: ProjectMetadata, reply: str
) -> None:
    llm = FakeLLM(reply, GOOD)

    result = run(llm, metadata)

    assert result.status is Status.REJECTED
    assert result.sql is None
    assert result.attempts == 1
    assert len(llm.prompts) == 1
    assert result.reason is not None
    assert result.reason.code == REASON_OUT_OF_SCOPE
    assert HANGUL.search(result.reason.message)


# ---- LLM 실패 ----


@pytest.mark.parametrize(
    "error", [LLMUnavailableError("연결 실패"), LLMTimeoutError("시간 초과")]
)
def test_llm_errors_are_not_swallowed(
    metadata: ProjectMetadata, error: Exception
) -> None:
    with pytest.raises(type(error)):
        run(FakeLLM(error), metadata)


def test_llm_error_during_a_retry_is_also_raised(metadata: ProjectMetadata) -> None:
    llm = FakeLLM(BAD_COLUMN, LLMUnavailableError("끊김"))

    with pytest.raises(LLMUnavailableError):
        run(llm, metadata)

    assert len(llm.prompts) == 2


# ---- 로그 ----


def test_validation_failures_are_logged_in_korean_without_the_sql(
    metadata: ProjectMetadata, caplog: pytest.LogCaptureFixture
) -> None:
    secret_sql = "SELECT SECRET_COLUMN_XYZ FROM OBJ_MAIN"
    generator = SqlGenerator(
        FakeLLM(secret_sql, GOOD), max_repair_attempts=2, max_rows=MAX_ROWS
    )

    with caplog.at_level(logging.WARNING, logger="text2sql.pipeline.run"):
        generator.run("질문", metadata, request_id="req-1")

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    assert "SQL 검증 실패" in messages[0]
    assert "req-1" in messages[0]
    assert "시도 1/3" in messages[0]
    assert "COLUMN_NOT_ALLOWED" in messages[0]
    assert HANGUL.search(messages[0])


# ---- 방언 오류 ----


def test_unknown_database_type_is_a_dialect_error(metadata: ProjectMetadata) -> None:
    odd = metadata.model_copy(
        update={
            "datasource": metadata.datasource.model_copy(update={"db_type": "mysql"})
        }
    )

    with pytest.raises(UnsupportedDbTypeError):
        run(FakeLLM(GOOD), odd)


# ---- extract_sql ----


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SELECT 1", "SELECT 1"),
        ("  SELECT 1  \n", "SELECT 1"),
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        ("설명입니다\n```sql\nSELECT 1\n```\n끝", "SELECT 1"),
        ("```SQL\n\nSELECT 1\n\n```", "SELECT 1"),
        ("", ""),
    ],
)
def test_extract_sql(text: str, expected: str) -> None:
    assert extract_sql(text) == expected
