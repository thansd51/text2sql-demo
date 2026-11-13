import re

import pytest

from text2sql.dialects import get_adapter

HANGUL = re.compile(r"[가-힣]")


@pytest.mark.parametrize(
    ("db_type", "db_version"),
    [
        ("oracle", "11g"),
        ("oracle", "19c"),
        ("postgresql", "14"),
        ("postgresql", "16.1"),
    ],
)
def test_rules_are_korean_and_name_the_database_and_version(
    db_type: str, db_version: str
) -> None:
    text = get_adapter(db_type, db_version).prompt_rules()

    assert HANGUL.search(text)
    assert db_version in text
    assert ("Oracle" if db_type == "oracle" else "PostgreSQL") in text
    assert all(line.startswith("- ") for line in text.splitlines())


def test_oracle_12c_or_later_tells_llm_to_use_fetch_first() -> None:
    for db_version in ("12c", "12.2", "19c", "23ai"):
        text = get_adapter("oracle", db_version).prompt_rules()
        assert "FETCH FIRST N ROWS ONLY를 사용합니다" in text, db_version


def test_oracle_before_12c_forbids_fetch_first_and_points_to_rownum() -> None:
    for db_version in ("9i", "11g", "11.2"):
        text = get_adapter("oracle", db_version).prompt_rules()
        assert "FETCH FIRST를 쓸 수 없습니다" in text, db_version
        assert "ROWNUM <= N" in text, db_version
        assert "FETCH FIRST N ROWS ONLY를 사용합니다" not in text, db_version


def test_oracle_rules_cover_the_oracle_pitfalls() -> None:
    text = get_adapter("oracle", "19c").prompt_rules()

    assert "별칭에는 AS를 쓰지 않습니다" in text  # design.md: 테이블 별칭에 AS 금지
    assert "IS NULL" in text  # 빈 문자열은 NULL
    assert "VARCHAR2(100)" in text  # CAST 길이
    assert "DUAL" in text
    assert "SYSDATE" in text  # 현재 날짜 함수 금지


def test_postgresql_rules_use_limit_and_no_oracle_terms() -> None:
    text = get_adapter("postgresql", "14").prompt_rules()

    assert "LIMIT N" in text
    for oracle_only in ("ROWNUM", "FETCH FIRST", "DUAL", "VARCHAR2", "SYSDATE"):
        assert oracle_only not in text, oracle_only


def test_rules_differ_by_database() -> None:
    assert (
        get_adapter("oracle", "19c").prompt_rules()
        != get_adapter("postgresql", "14").prompt_rules()
    )


def test_rules_no_longer_mention_views() -> None:
    for db_type, version in (("oracle", "19c"), ("postgresql", "14")):
        text = get_adapter(db_type, version).prompt_rules()
        assert "뷰" not in text, db_type
        assert "v_object" not in text, db_type


def test_rules_tell_the_model_how_to_get_todays_date() -> None:
    oracle = get_adapter("oracle", "19c").prompt_rules()
    postgres = get_adapter("postgresql", "14").prompt_rules()

    assert "TO_CHAR(SYSDATE, 'YYYYMMDD')" in oracle
    assert "ADD_MONTHS" in oracle  # 쓸 수 없는 날짜 계산 함수를 알려 준다
    assert "TO_CHAR(CURRENT_DATE, 'YYYYMMDD')" in postgres
    assert "SYSDATE" not in postgres
