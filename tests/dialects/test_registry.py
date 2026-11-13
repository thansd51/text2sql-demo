import re

import pytest
import sqlglot

from text2sql.dialects import (
    DialectError,
    InvalidDbVersionError,
    UnsupportedDbTypeError,
    get_adapter,
    supported_db_types,
)

HANGUL = re.compile(r"[가-힣]")


def test_supported_db_types() -> None:
    assert supported_db_types() == ("oracle", "postgresql")


@pytest.mark.parametrize(
    ("db_type", "sqlglot_dialect"), [("oracle", "oracle"), ("postgresql", "postgres")]
)
def test_sqlglot_dialect_name_is_valid_for_sqlglot(
    db_type: str, sqlglot_dialect: str
) -> None:
    adapter = get_adapter(db_type, "14")

    assert adapter.db_type == db_type
    assert adapter.sqlglot_dialect == sqlglot_dialect
    # 실제로 sqlglot이 이 이름을 받아들이는지 확인한다
    sqlglot.parse_one("SELECT 1 FROM t", read=adapter.sqlglot_dialect)


@pytest.mark.parametrize("db_type", ["mysql", "hana", "Oracle", "", "oracle "])
def test_unsupported_db_type_has_clear_korean_error(db_type: str) -> None:
    with pytest.raises(UnsupportedDbTypeError) as info:
        get_adapter(db_type, "1")

    assert info.value.code == "UNSUPPORTED_DB_TYPE"
    assert HANGUL.search(info.value.message)
    assert "oracle" in info.value.message
    assert "postgresql" in info.value.message
    assert isinstance(info.value, DialectError)


@pytest.mark.parametrize("db_version", ["", "abc", "c19", " ", "v12"])
def test_unreadable_version_has_korean_error(db_version: str) -> None:
    with pytest.raises(InvalidDbVersionError) as info:
        get_adapter("oracle", db_version)

    assert info.value.code == "INVALID_DB_VERSION"
    assert HANGUL.search(info.value.message)


@pytest.mark.parametrize(
    ("db_version", "major"),
    [("19c", 19), ("12.2", 12), ("12c", 12), ("11g", 11), ("11.2.0.4", 11), (" 9i", 9)],
)
def test_major_version_is_read_from_version_string(db_version: str, major: int) -> None:
    adapter = get_adapter("oracle", db_version)

    assert adapter.major_version == major  # type: ignore[attr-defined]
    assert adapter.db_version == db_version


def test_extra_functions_are_the_server_inserted_date_functions() -> None:
    from sqlglot import exp

    assert get_adapter("oracle", "19c").extra_functions == (exp.CurrentTimestamp,)
    assert get_adapter("postgresql", "14").extra_functions == (exp.CurrentDate,)
