import logging
import re
import uuid

import pytest

from tests.api.conftest import GOOD, URL, HarnessFactory, two_datasources
from text2sql.llm import LLMTimeoutError, LLMUnavailableError

HANGUL = re.compile(r"[가-힣]")
BODY = {"question": "상품 이름을 알려줘", "datasource_id": "p001"}

# 시험용 profile(tests/semantic/helpers.py)에서 GOOD이 Oracle 19c의 최종 SQL이 되면 이 모양이다
# (기본 행 제한 1000). 모델이 쓴 실제 테이블과 컬럼이 그대로 있다.
FINAL_ORACLE_SQL = (
    "SELECT * FROM (SELECT OBJ_NAME FROM OBJ_MAIN WHERE SID = 1) WHERE ROWNUM <= 1000"
)


# ---- 성공 ----


def test_success_response_has_the_contract_fields(make_harness: HarnessFactory) -> None:
    harness = make_harness(GOOD)

    response = harness.client.post(URL, json=BODY)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "request_id",
        "status",
        "sql",
        "references",
        "metadata_version",
        "message",
    }
    assert body["status"] == "OK"
    # 뷰 이름만 쓰던 SQL이 아니라, 뷰 정의가 들어간 실행 가능한 최종 SQL이다
    assert body["sql"] == FINAL_ORACLE_SQL
    assert body["references"] == [{"table": "OBJ_MAIN", "columns": ["SID", "OBJ_NAME"]}]
    assert body["metadata_version"] == harness.registry.get("p001").metadata_version  # type: ignore[union-attr]
    assert body["message"] is None


def test_request_id_is_a_uuid4_by_default(make_harness: HarnessFactory) -> None:
    body = make_harness(GOOD).client.post(URL, json=BODY).json()

    parsed = uuid.UUID(body["request_id"])
    assert parsed.version == 4


def test_each_request_gets_its_own_request_id(make_harness: HarnessFactory) -> None:
    harness = make_harness(GOOD, GOOD)

    first = harness.client.post(URL, json=BODY).json()["request_id"]
    second = harness.client.post(URL, json=BODY).json()["request_id"]

    assert first != second


@pytest.mark.parametrize(
    "header", ["abc-123_DEF", "a" * 64, "7f2c0e6e-1111-4222-8333-444455556666"]
)
def test_safe_x_request_id_header_is_used(
    make_harness: HarnessFactory, header: str
) -> None:
    response = make_harness(GOOD).client.post(
        URL, json=BODY, headers={"X-Request-Id": header}
    )

    assert response.json()["request_id"] == header


@pytest.mark.parametrize(
    "header",
    ["a" * 65, "has space", "x;y", "a\tb", "../etc", "<script>", "a.b", "a/b"],
)
def test_unsafe_x_request_id_header_is_replaced(
    make_harness: HarnessFactory, header: str
) -> None:
    response = make_harness(GOOD).client.post(
        URL, json=BODY, headers={"X-Request-Id": header}
    )

    request_id = response.json()["request_id"]
    assert request_id != header
    assert uuid.UUID(request_id).version == 4


def test_question_is_stripped_and_sent_to_the_llm(make_harness: HarnessFactory) -> None:
    harness = make_harness(GOOD)

    harness.client.post(URL, json={**BODY, "question": "   상품 몇 개야?  \n"})

    assert harness.llm.prompts[0][1].content == "질문: 상품 몇 개야?"


def test_the_datasource_selects_the_database_dialect(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(GOOD, GOOD, datasources=two_datasources())

    harness.client.post(URL, json={**BODY, "datasource_id": "p001"})
    harness.client.post(URL, json={**BODY, "datasource_id": "a-pg"})

    oracle_system = harness.llm.prompts[0][0].content
    postgres_system = harness.llm.prompts[1][0].content
    assert "Oracle 19c" in oracle_system
    assert "PostgreSQL 14" in postgres_system


def test_retry_then_success_is_a_normal_ok_response(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness("SELECT NO_SUCH FROM OBJ_MAIN", GOOD)

    body = harness.client.post(URL, json=BODY).json()

    assert body["status"] == "OK"
    assert body["sql"] == FINAL_ORACLE_SQL
    assert "no_such" not in body["sql"]
    assert len(harness.llm.prompts) == 2


# ---- 거부 (HTTP 200) ----


def test_rejected_after_retries_is_http_200_with_null_sql_and_korean_message(
    make_harness: HarnessFactory,
) -> None:
    bad = "SELECT * FROM OBJ_DETAIL"
    harness = make_harness(bad, bad, bad, max_repair_attempts=2)

    response = harness.client.post(URL, json=BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["sql"] is None
    assert body["references"] == []
    assert HANGUL.search(body["message"])
    assert "OBJ_DETAIL" not in response.text  # 거부된 SQL은 응답에 싣지 않는다
    assert body["metadata_version"]
    assert uuid.UUID(body["request_id"])
    assert len(harness.llm.prompts) == 3


def test_unsupported_question_is_rejected_with_a_message(
    make_harness: HarnessFactory,
) -> None:
    body = make_harness("UNSUPPORTED").client.post(URL, json=BODY).json()

    assert body["status"] == "REJECTED"
    assert body["sql"] is None
    assert "답할 수 없습니다" in body["message"]


def test_create_view_from_the_llm_is_never_returned(
    make_harness: HarnessFactory,
) -> None:
    sql = "CREATE VIEW v AS SELECT SID FROM OBJ_MAIN"
    harness = make_harness(sql, sql, sql)

    response = harness.client.post(URL, json=BODY)

    assert response.json()["status"] == "REJECTED"
    assert response.json()["sql"] is None
    assert "CREATE" not in response.text


# ---- 400: 미등록 datasource_id ----


@pytest.mark.parametrize(
    "datasource_id",
    [
        "nope",
        "P001",
        "p001 ",
        "../datasources/p001",
        "..\\p001",
        "p001.json",
        "p001/../p001",
        "%2e%2e",
        "한글",
    ],
)
def test_unregistered_datasource_id_is_400(
    make_harness: HarnessFactory, datasource_id: str
) -> None:
    harness = make_harness(GOOD)

    response = harness.client.post(URL, json={**BODY, "datasource_id": datasource_id})

    assert response.status_code == 400
    assert response.json() == {
        "code": "DATASOURCE_NOT_FOUND",
        "message": "등록되지 않은 데이터소스입니다",
    }
    assert harness.llm.prompts == []  # LLM을 호출하지 않는다


# ---- 400: 잘못된 요청 ----


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"datasource_id": "p001"}, "question"),
        ({"question": "질문"}, "datasource_id"),
        ({}, "datasource_id"),
        ({"question": "", "datasource_id": "p001"}, "question"),
        ({"question": "   \n\t ", "datasource_id": "p001"}, "question"),
        ({"question": 123, "datasource_id": "p001"}, "question"),
        ({"question": None, "datasource_id": "p001"}, "question"),
        ({"question": ["a"], "datasource_id": "p001"}, "question"),
        ({"question": "질문", "datasource_id": ""}, "datasource_id"),
        ({"question": "질문", "datasource_id": 1}, "datasource_id"),
        ({"question": "질문", "datasource_id": None}, "datasource_id"),
    ],
)
def test_invalid_request_is_400_with_the_field_names(
    make_harness: HarnessFactory, payload: dict[str, object], field: str
) -> None:
    harness = make_harness(GOOD)

    response = harness.client.post(URL, json=payload)

    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "INVALID_REQUEST"
    assert HANGUL.search(body["message"])
    assert field in body["message"]
    assert harness.llm.prompts == []


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        ("{깨진 json", "application/json"),
        ("", "application/json"),
        ("[1, 2]", "application/json"),
        ('"문자열"', "application/json"),
        ("question=a&datasource_id=p001", "application/x-www-form-urlencoded"),
    ],
)
def test_unparsable_or_wrong_shaped_body_is_400(
    make_harness: HarnessFactory, content: str, content_type: str
) -> None:
    harness = make_harness(GOOD)

    response = harness.client.post(
        URL, content=content, headers={"content-type": content_type}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert set(response.json()) == {"code", "message"}
    assert harness.llm.prompts == []


def test_invalid_json_message_is_specific(make_harness: HarnessFactory) -> None:
    response = make_harness(GOOD).client.post(
        URL, content="{깨진", headers={"content-type": "application/json"}
    )

    assert response.json()["message"] == "요청 본문이 올바른 JSON 형식이 아닙니다"


def test_invalid_request_message_does_not_echo_the_input(
    make_harness: HarnessFactory,
) -> None:
    secret = "SECRET-VALUE-12345"

    response = make_harness(GOOD).client.post(
        URL, json={"question": {"x": secret}, "datasource_id": "p001"}
    )

    assert response.status_code == 400
    assert secret not in response.text


def test_question_length_limit_comes_from_settings(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(GOOD, max_question_length=10)

    ok = harness.client.post(URL, json={**BODY, "question": "가" * 10})
    too_long = harness.client.post(URL, json={**BODY, "question": "가" * 11})

    assert ok.status_code == 200
    assert too_long.status_code == 400
    assert too_long.json() == {
        "code": "INVALID_REQUEST",
        "message": "질문이 너무 깁니다 (최대 10자)",
    }
    assert len(harness.llm.prompts) == 1  # 긴 질문은 LLM까지 가지 않는다


def test_question_length_is_measured_after_stripping(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(GOOD, max_question_length=10)

    response = harness.client.post(
        URL, json={**BODY, "question": "   " + "가" * 10 + "   "}
    )

    assert response.status_code == 200


# ---- 503: LLM 사용 불가 ----


def test_llm_unavailable_is_503(make_harness: HarnessFactory) -> None:
    harness = make_harness(LLMUnavailableError("연결 실패: 내부 주소 10.0.0.1"))

    response = harness.client.post(URL, json=BODY)

    assert response.status_code == 503
    assert response.json() == {
        "code": "LLM_UNAVAILABLE",
        "message": "LLM을 사용할 수 없습니다",
    }
    assert "10.0.0.1" not in response.text  # 내부 사정은 응답에 싣지 않는다


def test_llm_timeout_is_also_503(make_harness: HarnessFactory) -> None:
    response = make_harness(LLMTimeoutError("느림")).client.post(URL, json=BODY)

    assert response.status_code == 503
    assert response.json() == {
        "code": "LLM_TIMEOUT",
        "message": "LLM 응답 시간이 초과되었습니다",
    }


def test_llm_failure_during_a_retry_is_503_too(make_harness: HarnessFactory) -> None:
    harness = make_harness("SELECT NO_SUCH FROM OBJ_MAIN", LLMUnavailableError("끊김"))

    assert harness.client.post(URL, json=BODY).status_code == 503


# ---- 500: 예상하지 못한 오류 ----


def test_unexpected_error_is_500_with_the_same_error_shape(
    make_harness: HarnessFactory, caplog: pytest.LogCaptureFixture
) -> None:
    harness = make_harness(
        RuntimeError("SECRET-INTERNAL-DETAIL"), raise_server_exceptions=False
    )

    with caplog.at_level(logging.ERROR, logger="text2sql.api.errors"):
        response = harness.client.post(URL, json=BODY)

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "서버 내부 오류입니다",
    }
    assert "SECRET-INTERNAL-DETAIL" not in response.text
    assert any("예상하지 못한 오류" in record.getMessage() for record in caplog.records)


# ---- 로그 ----


def test_completion_is_logged_in_korean_without_the_question(
    make_harness: HarnessFactory, caplog: pytest.LogCaptureFixture
) -> None:
    harness = make_harness(GOOD)

    with caplog.at_level(logging.INFO, logger="text2sql.api.text_to_sql"):
        harness.client.post(
            URL,
            json={**BODY, "question": "비밀스러운 질문 내용"},
            headers={"X-Request-Id": "req-9"},
        )

    messages = [record.getMessage() for record in caplog.records]
    assert any("요청 처리 완료" in m and "req-9" in m and "p001" in m for m in messages)
    assert not any("비밀스러운 질문 내용" in m for m in messages)


# ---- 메서드와 형식 ----


def test_only_post_is_allowed_on_text_to_sql(make_harness: HarnessFactory) -> None:
    assert make_harness(GOOD).client.get(URL).status_code == 405


# ---- 최종 SQL (설계서 5~6단계) ----


def test_the_response_sql_uses_the_models_real_tables_and_columns(
    make_harness: HarnessFactory,
) -> None:
    body = make_harness(GOOD).client.post(URL, json=BODY).json()

    assert body["sql"] == FINAL_ORACLE_SQL
    assert "OBJ_MAIN" in body["sql"]
    assert "WITH" not in body["sql"]  # 뷰 정의를 끼워 넣지 않는다


def test_the_row_limit_comes_from_the_max_rows_setting(
    make_harness: HarnessFactory,
) -> None:
    body = make_harness(GOOD, max_rows=7).client.post(URL, json=BODY).json()

    assert body["sql"].endswith("WHERE ROWNUM <= 7")


def test_postgresql_datasource_gets_a_limit_clause(
    make_harness: HarnessFactory,
) -> None:
    harness = make_harness(GOOD, datasources=two_datasources())

    body = harness.client.post(URL, json={**BODY, "datasource_id": "a-pg"}).json()

    assert body["status"] == "OK"
    assert body["sql"].endswith("LIMIT 1000")
    assert "ROWNUM" not in body["sql"]


def test_a_broken_server_side_sql_is_a_500_without_details(
    make_harness: HarnessFactory,
) -> None:
    from text2sql.pipeline import FinalValidationError

    class BrokenGenerator:
        def run(self, *args: object, **kwargs: object) -> None:
            raise FinalValidationError(
                "서버가 만든 SQL이 최종 검증을 통과하지 못했습니다 (OBJ_MAIN)"
            )

    harness = make_harness(GOOD, raise_server_exceptions=False)
    harness.client.app.state.generator = BrokenGenerator()  # type: ignore[attr-defined]

    response = harness.client.post(URL, json=BODY)

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "서버 내부 오류입니다",
    }
    assert "OBJ_MAIN" not in response.text


def test_the_response_has_table_references_not_view_references(
    make_harness: HarnessFactory,
) -> None:
    sql = "SELECT T3.OBJ_NAME FROM OBJ_MAIN T1, OBJ_INV T2, OBJ_MAIN T3 WHERE T1.SID = T2.SID AND T2.SUBSID = T3.SID"

    body = make_harness(sql).client.post(URL, json=BODY).json()

    assert body["references"] == [
        {"table": "OBJ_INV", "columns": ["SID", "SUBSID"]},
        {"table": "OBJ_MAIN", "columns": ["SID", "OBJ_NAME"]},
    ]
    assert all("view" not in ref for ref in body["references"])
