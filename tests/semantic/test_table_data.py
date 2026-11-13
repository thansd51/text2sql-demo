"""semantic: 프로젝트마다 다른 테이블 데이터. 파일 최상위가 바로 {테이블: [행...]}이다.

같은 코드도 프로젝트마다 이름이 다를 수 있다(101이 어느 프로젝트에선 장기상품, 다른 프로젝트에선
정기보험). 이름은 코드 컬럼의 속성이 아니라 같은 행의 다른 컬럼(OBJ_NAME)에 있는 값이므로,
행 하나에 컬럼 여러 개를 함께 적는다. 값이 없는 컬럼도 컬럼 이름은 적고 ""(빈 값)로 둔다. null은 쓰지 않는다.
"""

import re
from pathlib import Path
from typing import Any

import pytest

from tests.semantic.helpers import DATASOURCE, PRODUCT_YAML, make_dirs
from text2sql.semantic import MetadataError, build_registry, iter_rows

HANGUL = re.compile(r"[가-힣]")

PROFILE = {
    "product.yml": PRODUCT_YAML.split("relationships:")[0].rstrip() + "\n",
    "tables/OBJ_MAIN.yml": """\
name: OBJ_MAIN
columns:
  - name: SID
    type: number
  - name: TYPEID
    type: number
  - name: R10_1
    type: string
  - name: OBJ_NAME
    type: string
""",
    "tables/OBJINV_TYPE.yml": """\
name: OBJINV_TYPE
columns:
  - name: INV_TYPE
    type: number
  - name: TYPE_GBN
    type: number
  - name: TYPE_NAME
    type: string
""",
}


def main_row(typeid: str, name: str, r10: str = "") -> dict:
    return {"TYPEID": typeid, "OBJ_NAME": name, "R10_1": r10}


def registry_for(tmp_path: Path, semantic: dict[str, Any] | str):
    dirs = make_dirs(
        tmp_path,
        semantics={"p001": semantic},
        profiles={"innoproduct": PROFILE},
    )
    return build_registry(dirs.repository())


def failure(tmp_path: Path, semantic: dict[str, Any] | str) -> str:
    with pytest.raises(MetadataError) as info:
        registry_for(tmp_path, semantic)
    return info.value.message


# ---- 행 하나에 컬럼 여러 개 ----


def test_a_row_keeps_the_code_and_the_name_side_by_side(tmp_path: Path) -> None:
    metadata = registry_for(
        tmp_path,
        {"OBJ_MAIN": [main_row("101", "장기상품", "#S00000031")]},
    ).get("p001")

    assert metadata is not None
    row = metadata.table_data["OBJ_MAIN"][0]
    assert row == {"TYPEID": "101", "OBJ_NAME": "장기상품", "R10_1": "#S00000031"}


def test_a_column_without_a_value_stays_in_the_row_as_an_empty_string(
    tmp_path: Path,
) -> None:
    metadata = registry_for(
        tmp_path,
        {
            "OBJ_MAIN": [
                main_row("101", "장기상품"),
                main_row("0", "보장기간", "#S00000031"),
            ]
        },
    ).get("p001")

    assert metadata is not None
    first, second = metadata.table_data["OBJ_MAIN"]
    assert list(first) == ["TYPEID", "OBJ_NAME", "R10_1"]  # 컬럼 이름은 남는다
    assert first["R10_1"] == ""
    assert second["R10_1"] == "#S00000031"


def test_rows_of_several_tables_are_kept_apart_by_table(tmp_path: Path) -> None:
    metadata = registry_for(
        tmp_path,
        {
            "OBJ_MAIN": [main_row("1", "장기상품")],
            "OBJINV_TYPE": [{"INV_TYPE": "1", "TYPE_GBN": "1", "TYPE_NAME": "기본"}],
        },
    ).get("p001")

    # 같은 값 "1"이 서로 다른 테이블.컬럼에서 각각 다른 뜻이다
    assert metadata is not None
    assert metadata.table_data["OBJ_MAIN"][0]["TYPEID"] == "1"
    assert metadata.table_data["OBJINV_TYPE"][0]["INV_TYPE"] == "1"
    assert list(metadata.table_data) == ["OBJ_MAIN", "OBJINV_TYPE"]


def test_the_order_of_tables_rows_and_columns_is_kept(tmp_path: Path) -> None:
    metadata = registry_for(
        tmp_path,
        {
            "OBJINV_TYPE": [{"TYPE_NAME": "b", "INV_TYPE": "2"}],
            "OBJ_MAIN": [main_row("3", "c"), main_row("1", "a")],
        },
    ).get("p001")

    assert metadata is not None
    assert list(metadata.table_data) == ["OBJINV_TYPE", "OBJ_MAIN"]
    assert list(metadata.table_data["OBJINV_TYPE"][0]) == ["TYPE_NAME", "INV_TYPE"]
    assert [r["TYPEID"] for r in metadata.table_data["OBJ_MAIN"]] == ["3", "1"]


def test_iter_rows_walks_tables_and_rows_in_file_order(tmp_path: Path) -> None:
    metadata = registry_for(
        tmp_path,
        {
            "OBJ_MAIN": [main_row("1", "a"), main_row("2", "b")],
            "OBJINV_TYPE": [{"INV_TYPE": "9"}],
        },
    ).get("p001")

    assert metadata is not None
    assert [
        (t, r.get("TYPEID") or r.get("INV_TYPE"))
        for t, r in iter_rows(metadata.table_data)
    ] == [
        ("OBJ_MAIN", "1"),
        ("OBJ_MAIN", "2"),
        ("OBJINV_TYPE", "9"),
    ]


def test_table_and_column_names_match_the_profile_regardless_of_case(
    tmp_path: Path,
) -> None:
    metadata = registry_for(
        tmp_path, {"obj_main": [{"typeid": "101", "obj_name": "장기상품"}]}
    ).get("p001")

    assert metadata is not None
    assert metadata.table_data


def test_without_data_there_are_no_rows(tmp_path: Path) -> None:
    assert registry_for(tmp_path, {}).get("p001").table_data == {}  # type: ignore[union-attr]


# ---- 프로젝트마다 같은 코드의 이름이 다르다 ----


def test_the_same_code_has_a_different_name_in_each_project(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        datasources={
            "p001": DATASOURCE,
            "p002": {**DATASOURCE, "id": "p002"},
            "p003": {**DATASOURCE, "id": "p003"},
        },
        semantics={
            # 101, 102는 모두에게 있지만 이름이 다르다. 111은 p002에만, 121은 p003에만 있다.
            "p001": {
                "OBJ_MAIN": [main_row("101", "장기상품"), main_row("102", "일반상품")]
            },
            "p002": {
                "OBJ_MAIN": [
                    main_row("101", "정기보험"),
                    main_row("102", "종신보험"),
                    main_row("111", "특약"),
                ]
            },
            "p003": {
                "OBJ_MAIN": [main_row("101", "연금상품"), main_row("121", "부가서비스")]
            },
        },
        profiles={"innoproduct": PROFILE},
    )

    registry = build_registry(dirs.repository())
    names = {
        pid: {
            r["TYPEID"]: r["OBJ_NAME"] for r in registry.get(pid).table_data["OBJ_MAIN"]
        }  # type: ignore[union-attr]
        for pid in ("p001", "p002", "p003")
    }

    assert names["p001"] == {"101": "장기상품", "102": "일반상품"}
    assert names["p002"] == {"101": "정기보험", "102": "종신보험", "111": "특약"}
    assert names["p003"] == {"101": "연금상품", "121": "부가서비스"}
    p1, p2 = registry.get("p001"), registry.get("p002")
    assert p1.columns_by_table() == p2.columns_by_table()  # type: ignore[union-attr]


# ---- 시작 시 검사: profile에 있는 테이블과 컬럼이어야 한다 ----


def test_an_unknown_table_is_a_startup_error(tmp_path: Path) -> None:
    message = failure(tmp_path, {"OBJ_MIAN": [main_row("1", "a")]})

    assert "semantic/p001.json: OBJ_MIAN: profile에 없는 테이블입니다" in message
    assert HANGUL.search(message)


def test_an_unknown_column_is_a_startup_error(tmp_path: Path) -> None:
    message = failure(tmp_path, {"OBJ_MAIN": [{"TYPEIDD": "1", "OBJ_NAME": "a"}]})

    assert "semantic/p001.json: OBJ_MAIN.TYPEIDD: profile에 없는 컬럼입니다" in message
    assert "OBJ_NAME" not in message  # 맞는 컬럼은 문제로 나오지 않는다


def test_a_column_of_another_table_is_not_accepted(tmp_path: Path) -> None:
    message = failure(tmp_path, {"OBJ_MAIN": [{"TYPE_NAME": "x"}]})

    assert "OBJ_MAIN.TYPE_NAME: profile에 없는 컬럼입니다" in message


def test_every_bad_table_and_column_is_reported_together(tmp_path: Path) -> None:
    with pytest.raises(MetadataError) as info:
        registry_for(
            tmp_path,
            {
                "NOPE": [{"A": "1"}],
                "OBJ_MAIN": [{"TYPEID": "1", "ZZZ": "2"}],
            },
        )

    assert len(info.value.problems) == 2


# ---- 형식 오류 ----


def test_duplicate_table_keys_in_the_json_file_are_rejected(tmp_path: Path) -> None:
    # JSON 파서는 같은 키가 두 번 나오면 뒤의 값만 남긴다. 조용히 사라지지 않게 거부한다.
    text = """{
  "OBJ_MAIN": [ { "TYPEID": "1", "OBJ_NAME": "a" } ],
  "OBJ_MAIN": [ { "TYPEID": "2", "OBJ_NAME": "b" } ]
}"""

    assert "semantic/p001.json: 같은 키가 두 번 적혀 있습니다: OBJ_MAIN" in failure(
        tmp_path, text
    )


def test_duplicate_column_keys_in_a_row_are_rejected(tmp_path: Path) -> None:
    text = '{ "OBJ_MAIN": [ { "TYPEID": "1", "TYPEID": "2" } ] }'

    assert "같은 키가 두 번 적혀 있습니다: TYPEID" in failure(tmp_path, text)


def test_table_keys_that_differ_only_in_case_are_duplicates(tmp_path: Path) -> None:
    message = failure(
        tmp_path,
        {"OBJ_MAIN": [main_row("1", "a")], "obj_main": [main_row("2", "b")]},
    )

    assert "테이블 이름이(가) 중복됩니다: OBJ_MAIN" in message


def test_column_keys_that_differ_only_in_case_are_duplicates(tmp_path: Path) -> None:
    message = failure(tmp_path, {"OBJ_MAIN": [{"TYPEID": "1", "typeid": "2"}]})

    assert "컬럼 이름이(가) 중복됩니다: TYPEID" in message


def test_rows_of_one_table_must_share_the_same_columns(tmp_path: Path) -> None:
    # 값이 없는 컬럼도 컬럼 이름은 적는다 (""). 행마다 컬럼이 다르면 거부한다.
    message = failure(
        tmp_path,
        {
            "OBJ_MAIN": [
                {"TYPEID": "101", "OBJ_NAME": "장기상품", "R10_1": ""},
                {"TYPEID": "0", "OBJ_NAME": "보장기간"},
            ]
        },
    )

    assert "OBJ_MAIN" in message
    assert "1번째 행의 컬럼이 첫 행과 다릅니다" in message
    assert '""' in message


def test_an_empty_row_list_and_an_empty_row_are_rejected(tmp_path: Path) -> None:
    assert "행이 1개 이상 있어야 합니다" in failure(tmp_path, {"OBJ_MAIN": []})
    assert "행에는 컬럼이 1개 이상 있어야 합니다" in failure(
        tmp_path, {"OBJ_MAIN": [{}]}
    )


def test_the_same_row_twice_is_rejected(tmp_path: Path) -> None:
    message = failure(
        tmp_path,
        {"OBJ_MAIN": [main_row("101", "장기상품"), main_row("101", "장기상품")]},
    )

    assert "같은 행이 두 번 적혀 있습니다" in message


def test_the_same_code_with_two_different_names_is_allowed(tmp_path: Path) -> None:
    # 같은 코드가 이름만 다른 행으로 두 번 나올 수 있다 (실제 데이터가 그럴 수 있다)
    metadata = registry_for(
        tmp_path,
        {"OBJ_MAIN": [main_row("101", "장기상품"), main_row("101", "장기보험")]},
    ).get("p001")

    assert metadata is not None
    assert len(metadata.table_data["OBJ_MAIN"]) == 2


@pytest.mark.parametrize("value", [101, 1.5, True, ["a"], {"a": 1}, None])
def test_values_must_be_strings(tmp_path: Path, value: object) -> None:
    message = failure(tmp_path, {"OBJ_MAIN": [{"TYPEID": value, "OBJ_NAME": "a"}]})

    assert "semantic/p001.json: OBJ_MAIN[0].TYPEID" in message
    assert HANGUL.search(message)


def test_null_is_not_accepted_and_the_message_says_to_use_an_empty_string(
    tmp_path: Path,
) -> None:
    message = failure(tmp_path, {"OBJ_MAIN": [{"TYPEID": "1", "OBJ_NAME": None}]})

    assert "semantic/p001.json: OBJ_MAIN[0].OBJ_NAME" in message
    assert 'null이 아니라 ""로 적으세요' in message


def test_a_numeric_code_gets_the_quote_hint(tmp_path: Path) -> None:
    message = failure(tmp_path, {"OBJ_MAIN": [{"TYPEID": 101, "OBJ_NAME": "a"}]})

    assert '"100"' in message  # 숫자 코드는 따옴표로 감싸라는 안내


@pytest.mark.parametrize("bad", ["1 2", "OBJ-MAIN", "1ABC", "한글"])
def test_table_and_column_names_must_be_plain_identifiers(
    tmp_path: Path, bad: str
) -> None:
    assert "형식이 올바르지 않습니다" in failure(tmp_path, {bad: [{"TYPEID": "1"}]})
    assert "형식이 올바르지 않습니다" in failure(tmp_path, {"OBJ_MAIN": [{bad: "1"}]})


@pytest.mark.parametrize(
    "old_style",
    [
        # 예전 형식: code_catalog 아래에 {테이블: {컬럼: [{code, name}]}}
        {
            "code_catalog": {
                "OBJ_MAIN": {"TYPEID": [{"code": "101", "name": "장기상품"}]}
            }
        },
        # 예전 형식: glossary, relationships 문자열 목록
        {"glossary": ["프로젝트 용어"]},
        {"relationships": ["A.X = B.X"]},
        {"type_catalog": [{"type_id": "100", "name": "상품"}]},
    ],
)
def test_the_old_formats_are_rejected(tmp_path: Path, old_style: dict) -> None:
    message = failure(tmp_path, old_style)

    assert "semantic/p001.json:" in message
    assert HANGUL.search(message)


def test_examples_no_longer_belong_in_a_semantic_file(tmp_path: Path) -> None:
    # 예시는 제품 공통이라 examples/<제품>.yml에 둔다. 프로젝트 값 파일에는 두지 않는다.
    message = failure(
        tmp_path, {"examples": [{"question": "q", "sql": "SELECT 1 FROM T"}]}
    )

    assert "semantic/p001.json:" in message


# ---- 해시 ----


def test_metadata_version_changes_when_the_data_changes(tmp_path: Path) -> None:
    first = registry_for(tmp_path / "a", {"OBJ_MAIN": [main_row("101", "장기상품")]})
    second = registry_for(tmp_path / "b", {"OBJ_MAIN": [main_row("101", "일반상품")]})

    assert first.get("p001").metadata_version != second.get("p001").metadata_version  # type: ignore[union-attr]
