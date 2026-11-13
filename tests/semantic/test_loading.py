import re
from pathlib import Path
from typing import Any

import pytest

from tests.semantic.helpers import (
    DATASOURCE,
    EXAMPLES_YAML,
    OBJ_MAIN_YAML,
    PRODUCT_YAML,
    PROFILE_FILES,
    SEMANTIC,
    make_dirs,
)
from text2sql.semantic import FileRepository, MetadataError, build_registry

HANGUL = re.compile(r"[가-힣]")
REPO_ROOT = Path(__file__).resolve().parents[2]


def problems_of(info: pytest.ExceptionInfo[MetadataError]) -> str:
    return "\n".join(info.value.problems)


# ---- 정상 ----


def test_valid_files_load_and_build_registry(tmp_path: Path) -> None:
    registry = build_registry(
        make_dirs(tmp_path, examples={"innoproduct": EXAMPLES_YAML}).repository()
    )

    metadata = registry.get("p001")

    assert metadata is not None
    assert metadata.datasource.db_type == "oracle"
    assert metadata.datasource.db_version == "19c"
    assert metadata.datasource.profiles == ("innoproduct",)  # 기본값
    # 테이블은 파일 이름순으로 읽는다
    assert [table.name for table in metadata.tables] == ["OBJ_INV", "OBJ_MAIN"]
    assert metadata.columns_by_table() == {
        "OBJ_MAIN": ["SID", "BIZCODE", "TYPEID", "OBJ_NAME"],
        "OBJ_INV": ["SID", "SUBSID", "INV_TYPE"],
    }
    assert metadata.table_names() == {"OBJ_MAIN", "OBJ_INV"}
    assert metadata.get_table("OBJ_MAIN") is not None
    assert metadata.get_table("nope") is None
    # 프로젝트 데이터: 테이블 -> 행 목록 (행 하나에 컬럼 여러 개)
    assert metadata.table_data == {
        "OBJ_MAIN": (
            {"TYPEID": "101", "OBJ_NAME": "장기상품"},
            {"TYPEID": "102", "OBJ_NAME": "일반상품"},
        )
    }
    assert [item.render() for item in metadata.relationships] == [
        "OBJ_INV.SID = OBJ_MAIN.SID (상위 오브젝트)",
        "OBJ_INV.SUBSID = OBJ_MAIN.SID (하위 오브젝트)",
    ]
    assert metadata.glossary == ("오브젝트명은 중복될 수 있다",)
    assert [e.question for e in metadata.examples] == [
        "오브젝트 이름 목록",
        "유형코드가 101인 오브젝트의 코드와 이름",
    ]
    assert re.fullmatch(r"[0-9a-f]{12}", metadata.metadata_version)


def test_commas_in_descriptions_are_kept(tmp_path: Path) -> None:
    metadata = build_registry(make_dirs(tmp_path).repository()).get("p001")

    assert metadata is not None
    main = metadata.get_table("OBJ_MAIN")
    assert main is not None
    columns = main.columns
    assert columns[0].description == "고유 ID (PK, 중복 없음)"
    assert columns[3].synonyms == ("상품명", "이름")


def repo_repository() -> FileRepository:
    return FileRepository(
        REPO_ROOT / "datasources",
        REPO_ROOT / "semantic",
        REPO_ROOT / "profiles",
        REPO_ROOT / "examples",
    )


def test_the_sample_files_in_the_repository_load() -> None:
    metadata = build_registry(repo_repository()).get("p001")

    assert metadata is not None
    assert (metadata.datasource.db_type, metadata.datasource.db_version) == (
        "oracle",
        "19c",
    )
    # 실제 DB 테이블 단위로 정의돼 있다 (용도별 뷰가 아니다)
    # 테이블 파일 하나가 테이블 하나다 (파일 이름순)
    assert [table.name for table in metadata.tables] == [
        "OBJINV_TYPE",
        "OBJ_INV",
        "OBJ_MAIN",
    ]
    main = metadata.get_table("OBJ_MAIN")
    assert main is not None
    assert [c.name for c in main.columns] == [
        "SID",
        "BIZCODE",
        "TYPEID",
        "R10_1",
        "OBJ_NAME",
        "VF_DT",
        "VT_DT",
    ]
    # 설명 문구가 쉼표에서 잘리지 않는다
    assert main.columns[0].synonyms == ("내부ID", "오브젝트ID")
    assert "(PK, 중복 없음)" in main.columns[0].description
    assert len(metadata.examples) == 7  # 제품 공통 예시
    assert len(metadata.relationships) >= 4


def test_the_sample_table_data_is_grouped_by_table_and_keeps_rows_whole() -> None:
    metadata = build_registry(repo_repository()).get("p001")

    assert metadata is not None
    assert list(metadata.table_data) == ["OBJ_MAIN", "OBJINV_TYPE"]
    rows = metadata.table_data["OBJ_MAIN"]
    # 행 하나에 테이블 정의의 컬럼이 모두 있고, 값이 없는 컬럼은 ""로 남는다
    assert rows[0] == {
        "SID": "1001",
        "BIZCODE": "TYPE101",
        "TYPEID": "101",
        "R10_1": "",
        "OBJ_NAME": "장기상품",
        "VF_DT": "20200101",
        "VT_DT": "99991231",
    }
    assert rows[1]["OBJ_NAME"] == "일반상품"


def test_the_sample_tables_carry_their_own_rules() -> None:
    metadata = build_registry(repo_repository()).get("p001")

    assert metadata is not None
    main = metadata.get_table("OBJ_MAIN")
    assert main is not None
    assert any("TYPEID <> 0" in rule for rule in main.rules)
    inv = metadata.get_table("OBJ_INV")
    assert inv is not None
    assert any("TYPE_GBN" in rule for rule in inv.rules)
    # 테이블 전용 규칙은 전역 용어집에 남아 있지 않다
    assert not any("TYPEID <> 0" in line for line in metadata.glossary)


def test_semantic_file_is_optional(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path, semantics={})

    repository = dirs.repository()
    metadata = build_registry(repository).get("p001")

    assert metadata is not None
    assert metadata.table_data == {}
    assert metadata.glossary == ("오브젝트명은 중복될 수 있다",)
    assert repository.get_semantic("p001").tables == {}


def test_missing_semantic_directory_is_fine(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path, semantics={})
    dirs.semantic.rmdir()

    assert build_registry(dirs.repository()).get("p001") is not None


def test_datasources_are_listed_in_id_order(tmp_path: Path) -> None:
    other = {
        **DATASOURCE,
        "id": "a-first",
        "name": "다른 프로젝트",
        "db_type": "postgresql",
        "db_version": "14",
    }
    dirs = make_dirs(tmp_path, datasources={"p001": DATASOURCE, "a-first": other})

    registry = build_registry(dirs.repository())

    assert [d.id for d in dirs.repository().list_datasources()] == ["a-first", "p001"]
    assert [d.id for d in registry.datasources()] == ["a-first", "p001"]


def test_unknown_and_malicious_ids_are_just_misses(tmp_path: Path) -> None:
    repository = make_dirs(tmp_path).repository()
    registry = build_registry(repository)

    for datasource_id in ("nope", "../datasources/p001", "..\\p001", "", "p001.json"):
        assert registry.get(datasource_id) is None
        assert repository.get_datasource(datasource_id) is None


# ---- 필수 필드 누락 ----


@pytest.mark.parametrize("field", ["id", "name", "db_type", "db_version"])
def test_missing_datasource_field_is_reported_with_file_and_location(
    tmp_path: Path, field: str
) -> None:
    broken = {key: value for key, value in DATASOURCE.items() if key != field}
    dirs = make_dirs(tmp_path, datasources={"p001": broken})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert f"datasources/p001.json: {field}: 필수 항목이 없습니다" in problems_of(info)
    assert info.value.code == "METADATA_INVALID"


@pytest.mark.parametrize(
    ("old", "new", "location"),
    [
        ("name: OBJ_MAIN\ndescription: 오브젝트\n", "description: 오브젝트\n", "name"),
        (
            "  - name: SID\n    type: number\n    description: 고유 ID (PK, 중복 없음)\n",
            "  - name: SID\n    description: 고유 ID\n",
            "columns[0].type",
        ),
        (
            "  - name: BIZCODE\n    type: string\n",
            "  - type: string\n",
            "columns[1].name",
        ),
    ],
)
def test_missing_table_field_is_reported_with_yaml_location(
    tmp_path: Path, old: str, new: str, location: str
) -> None:
    assert old in OBJ_MAIN_YAML
    yaml_text = OBJ_MAIN_YAML.replace(old, new, 1)
    dirs = make_dirs(
        tmp_path,
        profiles={"innoproduct": {**PROFILE_FILES, "tables/OBJ_MAIN.yml": yaml_text}},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        f"profiles/innoproduct/tables/OBJ_MAIN.yml: {location}: 필수 항목이 없습니다"
        in problems_of(info)
    )


def test_a_table_without_columns_and_a_product_without_tables_are_reported(
    tmp_path: Path,
) -> None:
    dirs = make_dirs(
        tmp_path,
        profiles={
            "innoproduct": {
                "product.yml": "product: innoproduct\n",
                "tables/T.yml": "name: T\ncolumns: []\n",
            },
            "other": {"product.yml": "product: other\n"},
        },
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    text = problems_of(info)
    assert (
        "profiles/innoproduct/tables/T.yml: columns: columns에는 컬럼이 1개 이상 있어야 합니다"
        in text
    )
    assert (
        "profiles/other/tables/: 테이블 파일(<테이블>.yml)이 1개 이상 필요합니다"
        in text
    )


def test_unknown_fields_in_product_and_table_files_are_reported(
    tmp_path: Path,
) -> None:
    dirs = make_dirs(
        tmp_path,
        profiles={
            "innoproduct": {
                "product.yml": PRODUCT_YAML + "views:\n  - name: v_object\n",
                "tables/OBJ_MAIN.yml": OBJ_MAIN_YAML + "tpyo: 1\n",
            }
        },
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    text = problems_of(info)
    assert "profiles/innoproduct/product.yml: views: 알 수 없는 항목입니다" in text
    assert (
        "profiles/innoproduct/tables/OBJ_MAIN.yml: tpyo: 알 수 없는 항목입니다" in text
    )


def test_the_old_single_file_profile_is_reported_as_a_missing_directory(
    tmp_path: Path,
) -> None:
    dirs = make_dirs(tmp_path)
    (dirs.profiles / "innoproduct.yml").write_text("product: innoproduct\n")
    for path in sorted((dirs.profiles / "innoproduct").rglob("*"), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    (dirs.profiles / "innoproduct").rmdir()

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "제품 'innoproduct'에 해당하는 profiles/innoproduct/ 디렉터리가 없습니다"
        in problems_of(info)
    )


def test_missing_product_and_column_type(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        profiles={
            "innoproduct": {
                "product.yml": PRODUCT_YAML.replace("product: innoproduct\n", ""),
                "tables/OBJ_MAIN.yml": OBJ_MAIN_YAML.replace("    type: number\n", ""),
            }
        },
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    text = problems_of(info)
    assert "profiles/innoproduct/product.yml: product: 필수 항목이 없습니다" in text
    assert (
        "profiles/innoproduct/tables/OBJ_MAIN.yml: columns[0].type: 필수 항목이 없습니다"
        in text
    )


def test_a_missing_product_file_is_reported(tmp_path: Path) -> None:
    files = {k: v for k, v in PROFILE_FILES.items() if k != "product.yml"}
    dirs = make_dirs(tmp_path, profiles={"innoproduct": files})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "profiles/innoproduct/product.yml: 파일이 없습니다" in problems_of(info)


def test_the_table_file_name_must_match_the_table_name(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        profiles={
            "innoproduct": {**PROFILE_FILES, "tables/OBJ_OTHER.yml": OBJ_MAIN_YAML}
        },
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "profiles/innoproduct/tables/OBJ_OTHER.yml: name: 파일명(OBJ_OTHER)과 name(OBJ_MAIN)이 다릅니다"
        in problems_of(info)
    )


# ---- 값 오류 ----


@pytest.mark.parametrize("db_type", ["mysql", "Oracle", "postgres", "hana", ""])
def test_invalid_db_type(tmp_path: Path, db_type: str) -> None:
    dirs = make_dirs(tmp_path, datasources={"p001": {**DATASOURCE, "db_type": db_type}})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    text = problems_of(info)
    assert "datasources/p001.json: db_type:" in text
    assert "허용: oracle, postgresql" in text


@pytest.mark.parametrize("bad_id", ["P001", "p 001", "p.001", "한글", "p001/../x", ""])
def test_invalid_id_format(tmp_path: Path, bad_id: str) -> None:
    dirs = make_dirs(tmp_path, datasources={"p001": {**DATASOURCE, "id": bad_id}})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "datasources/p001.json: id:" in problems_of(info)


def test_invalid_semantic_file_name(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path, semantics={"P 001": SEMANTIC})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "semantic/P 001.json: 파일명이 id 형식이 아닙니다" in problems_of(info)


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"db_version": 19}, "db_version: 문자열이어야 합니다"),
        ({"db_version": ""}, "db_version: 비어 있을 수 없습니다"),
        ({"name": None}, "name: 문자열이어야 합니다"),
        ({"profiles": []}, "profiles: profiles에는 제품이 1개 이상"),
        ({"profiles": ["innoproduct", "innoproduct"]}, "제품 이름이(가) 중복됩니다"),
        ({"profiles": ["Bad Name"]}, "profiles[0]: 형식이 올바르지 않습니다"),
        ({"typo_field": 1}, "typo_field: 알 수 없는 항목입니다"),
    ],
)
def test_other_datasource_value_errors(
    tmp_path: Path, override: dict[str, Any], expected: str
) -> None:
    dirs = make_dirs(tmp_path, datasources={"p001": {**DATASOURCE, **override}})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert expected in problems_of(info)


def test_duplicate_column_names_are_rejected_ignoring_case(tmp_path: Path) -> None:
    yaml_text = OBJ_MAIN_YAML.replace(
        "  - name: OBJ_NAME",
        "  - name: sid\n    type: number\n  - name: OBJ_NAME",
    )
    dirs = make_dirs(
        tmp_path,
        profiles={"innoproduct": {**PROFILE_FILES, "tables/OBJ_MAIN.yml": yaml_text}},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "컬럼 이름이(가) 중복됩니다: SID" in problems_of(
        info
    )  # 대소문자만 다른 컬럼도 중복이다


@pytest.mark.parametrize(
    "column_name", ["1ABC", "OBJ-NAME", "상품명", "OBJ NAME", "_X"]
)
def test_table_and_column_names_must_be_plain_database_identifiers(
    tmp_path: Path, column_name: str
) -> None:
    yaml_text = OBJ_MAIN_YAML.replace("name: OBJ_NAME", f"name: {column_name!r}")
    dirs = make_dirs(
        tmp_path,
        profiles={"innoproduct": {**PROFILE_FILES, "tables/OBJ_MAIN.yml": yaml_text}},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "profiles/innoproduct/tables/OBJ_MAIN.yml: columns[3].name: 형식이 올바르지 않습니다"
        in problems_of(info)
    )


@pytest.mark.parametrize("name", ["OBJ_MAIN", "obj_main", "R10_1", "Obj_Main2"])
def test_real_database_names_in_any_case_are_accepted(
    tmp_path: Path, name: str
) -> None:
    yaml_text = OBJ_MAIN_YAML.replace("name: OBJ_NAME", f"name: {name}")

    dirs = make_dirs(
        tmp_path,
        profiles={"innoproduct": {**PROFILE_FILES, "tables/OBJ_MAIN.yml": yaml_text}},
    )

    assert dirs.repository().get_profile("innoproduct") is not None


# ---- 문법 오류 ----


@pytest.mark.parametrize(
    "content",
    ['{"id": "p001",', "{id: p001}", '{"id": "p001" "name": "x"}', "", "not json"],
)
def test_invalid_json_syntax(tmp_path: Path, content: str) -> None:
    dirs = make_dirs(tmp_path, datasources={"p001": content})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert re.search(
        r"datasources/p001\.json: \d+행 \d+열: JSON 문법이 올바르지 않습니다",
        problems_of(info),
    )


def test_invalid_json_in_semantic_file(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path, semantics={"p001": '{"glossary": ["a",]}'})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "semantic/p001.json:" in problems_of(info)
    assert "JSON 문법이 올바르지 않습니다" in problems_of(info)


def test_invalid_yaml_syntax(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        profiles={
            "innoproduct": {
                **PROFILE_FILES,
                "product.yml": "product: innoproduct\nviews: [\n  - name: x\n",
            }
        },
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert re.search(
        r"profiles/innoproduct/product\.yml: \d+행 \d+열: YAML 문법이 올바르지 않습니다",
        problems_of(info),
    )


@pytest.mark.parametrize("content", ["[1, 2]", '"text"', "123", "null"])
def test_top_level_must_be_an_object(tmp_path: Path, content: str) -> None:
    dirs = make_dirs(tmp_path, datasources={"p001": content})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "datasources/p001.json: (최상위): 객체(키: 값 묶음)여야 합니다"
        in problems_of(info)
    )


def test_non_utf8_file_is_reported(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path)
    (dirs.datasources / "p001.json").write_bytes('{"id": "가"}'.encode("cp949"))

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "datasources/p001.json: UTF-8 인코딩으로 읽을 수 없습니다" in problems_of(
        info
    )


def test_utf8_bom_is_accepted(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path)
    (dirs.datasources / "p001.json").write_bytes(
        b"\xef\xbb\xbf"
        + b'{"id":"p001","name":"x","db_type":"oracle","db_version":"19c"}'
    )

    assert build_registry(dirs.repository()).get("p001") is not None


# ---- 파일명과 id ----


def test_file_name_and_id_mismatch(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path, datasources={"p002": DATASOURCE}, semantics={})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "datasources/p002.json: id: 파일명(p002)과 id(p001)가 다릅니다"
        in problems_of(info)
    )


def test_profile_directory_name_and_product_mismatch(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path, profiles={"other": PROFILE_FILES})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "profiles/other/product.yml: product: 디렉터리명(other)과 product(innoproduct)가 다릅니다"
        in problems_of(info)
    )


# ---- 참조 오류 ----


def test_semantic_without_datasource_fails(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path, semantics={"p001": SEMANTIC, "p999": SEMANTIC})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "semantic/p999.json: 대응하는 datasources/p999.json이 없습니다"
        in problems_of(info)
    )


def test_unknown_profile_product_fails(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        datasources={"p001": {**DATASOURCE, "profiles": ["innoproduct", "ghost"]}},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "datasources/p001.json: profiles[1]: 제품 'ghost'에 해당하는 profiles/ghost/ 디렉터리가 없습니다"
        in problems_of(info)
    )


def test_missing_datasources_directory_fails(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path)
    for file in dirs.datasources.iterdir():
        file.unlink()
    dirs.datasources.rmdir()

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "datasources/: 데이터소스 디렉터리가 없습니다" in problems_of(info)


def test_all_problems_are_reported_together(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        datasources={"p001": {**DATASOURCE, "db_type": "mysql"}, "p002": '{"id":'},
        semantics={"p001": SEMANTIC, "ghost": SEMANTIC},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert len(info.value.problems) >= 3
    assert info.value.message.startswith(
        f"메타데이터 오류 {len(info.value.problems)}건:"
    )


def test_every_message_is_korean_and_does_not_echo_input(tmp_path: Path) -> None:
    secret = "SECRET-DB-VERSION"
    dirs = make_dirs(
        tmp_path,
        datasources={"p001": {**DATASOURCE, "db_type": secret, "typo": secret}},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    for problem in info.value.problems:
        assert HANGUL.search(problem), problem
    assert secret not in info.value.message


def test_non_json_and_hidden_files_are_ignored(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path)
    (dirs.datasources / "README.md").write_text("설명", encoding="utf-8")
    (dirs.datasources / ".p002.json").write_text("{", encoding="utf-8")
    (dirs.datasources / "p003.json.bak").write_text("{", encoding="utf-8")
    (dirs.profiles / "notes.txt").write_text("{", encoding="utf-8")
    (dirs.profiles / ".git").mkdir()  # 숨김 디렉터리는 제품이 아니다
    tables = dirs.profiles / "innoproduct" / "tables"
    (tables / "README.md").write_text("설명", encoding="utf-8")
    (tables / ".OBJ_X.yml").write_text("{", encoding="utf-8")

    assert [d.id for d in build_registry(dirs.repository()).datasources()] == ["p001"]


def test_name_column_must_be_a_column_of_the_table(tmp_path: Path) -> None:
    yaml_text = OBJ_MAIN_YAML.replace(
        "name: OBJ_MAIN\n", "name: OBJ_MAIN\nname_column: NO_SUCH\n", 1
    )
    dirs = make_dirs(
        tmp_path,
        profiles={"innoproduct": {**PROFILE_FILES, "tables/OBJ_MAIN.yml": yaml_text}},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "name_column 'NO_SUCH'이(가) 이 테이블의 컬럼에 없습니다" in problems_of(
        info
    )


def test_name_column_is_optional_and_case_insensitive(tmp_path: Path) -> None:
    yaml_text = OBJ_MAIN_YAML.replace(
        "name: OBJ_MAIN\n", "name: OBJ_MAIN\nname_column: obj_name\n", 1
    )
    dirs = make_dirs(
        tmp_path,
        profiles={"innoproduct": {**PROFILE_FILES, "tables/OBJ_MAIN.yml": yaml_text}},
    )

    metadata = build_registry(dirs.repository()).get("p001")

    assert metadata is not None
    assert metadata.get_table("OBJ_MAIN").name_column == "obj_name"  # type: ignore[union-attr]
    assert metadata.get_table("OBJ_INV").name_column is None  # type: ignore[union-attr]


def test_key_columns_must_be_columns_of_the_table(
    tmp_path: Path,
) -> None:
    yaml_text = OBJ_MAIN_YAML.replace(
        "name: OBJ_MAIN\n", "name: OBJ_MAIN\nkey_columns: [TYPEID, NO_SUCH]\n", 1
    )
    dirs = make_dirs(
        tmp_path,
        profiles={"innoproduct": {**PROFILE_FILES, "tables/OBJ_MAIN.yml": yaml_text}},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "key_columns 'NO_SUCH'이(가) 이 테이블의 컬럼에 없습니다" in problems_of(
        info
    )


def test_key_columns_may_not_repeat_a_column(tmp_path: Path) -> None:
    yaml_text = OBJ_MAIN_YAML.replace(
        "name: OBJ_MAIN\n", "name: OBJ_MAIN\nkey_columns: [TYPEID, typeid]\n", 1
    )
    dirs = make_dirs(
        tmp_path,
        profiles={"innoproduct": {**PROFILE_FILES, "tables/OBJ_MAIN.yml": yaml_text}},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert "key_columns이(가) 중복됩니다: TYPEID" in problems_of(info)
