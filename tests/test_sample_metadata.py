"""저장소의 샘플 파일(profiles/, examples/, semantic/, datasources/)이 서로 어긋나지 않는지 확인한다.

profile의 컬럼, 공통 예시, 프로젝트별 코드표는 사람이 따로 적는 값이라 오타가 나기 쉽다.
실제 DB는 없으므로 sqlglot으로 구조를 확인한다.
"""

import re
from pathlib import Path

import pytest
import yaml

from text2sql.dialects import get_adapter
from text2sql.pipeline import build_messages, check_example
from text2sql.semantic import (
    FileRepository,
    ProjectMetadata,
    Registry,
    build_registry,
    iter_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS = [f"p00{n}" for n in range(1, 7)]

# 알려 주신 컬럼 문서 그대로 (OBJ_MAIN의 VERCODE는 사용 안 함이라 뺐다)
EXPECTED_COLUMNS = {
    "OBJ_MAIN": ["SID", "BIZCODE", "TYPEID", "R10_1", "OBJ_NAME", "VF_DT", "VT_DT"],
    "OBJ_INV": [
        "INV_TYPE",
        "SID",
        "SUBSID",
        "SEQ",
        "VF_DT",
        "VT_DT",
        "PROP_SID",
        "SET_SEQ",
        "BASIS",
        "BASIS_YN",
        "REL_DESC",
        "RULEID",
    ],
    "OBJINV_TYPE": ["INV_TYPE", "TYPE_GBN", "TYPE_NAME", "END_DT"],
}


@pytest.fixture(scope="module")
def registry() -> Registry:
    repository = FileRepository(
        REPO_ROOT / "datasources",
        REPO_ROOT / "semantic",
        REPO_ROOT / "profiles",
        REPO_ROOT / "examples",
    )
    return build_registry(repository)


def project(registry: Registry, project_id: str) -> ProjectMetadata:
    metadata = registry.get(project_id)
    assert metadata is not None
    return metadata


def system_prompt(metadata: ProjectMetadata) -> str:
    adapter = get_adapter(metadata.datasource.db_type, metadata.datasource.db_version)
    return build_messages(metadata, adapter.prompt_rules(), "질문")[0].content


def type_names(metadata: ProjectMetadata) -> dict[str, str]:
    """OBJ_MAIN의 유형 행: {TYPEID: OBJ_NAME}. 항목코드(R10_1)가 없는 행이다."""
    return {
        row["TYPEID"]: row["OBJ_NAME"]
        for row in metadata.table_data.get("OBJ_MAIN", ())
        if not row.get("R10_1") and row["TYPEID"] and row["OBJ_NAME"]
    }


def item_names(metadata: ProjectMetadata) -> dict[str, str]:
    """OBJ_MAIN의 항목 행: {R10_1: OBJ_NAME}."""
    return {
        row["R10_1"]: row["OBJ_NAME"]
        for row in metadata.table_data.get("OBJ_MAIN", ())
        if row.get("R10_1") and row["OBJ_NAME"]
    }


def lookup_text(name: str, condition: str) -> str:
    """프롬프트에서 이름 행 한 줄이 보이는 모양 (이름: 그 행을 가리키는 조건)."""
    return f"- {name}: {condition}"


# ---- 파일 구성 ----


def test_the_repository_has_the_expected_dummy_projects(registry: Registry) -> None:
    on_disk = sorted(p.stem for p in (REPO_ROOT / "datasources").glob("*.json"))

    assert on_disk == PROJECTS
    assert [m.datasource.id for m in registry.all_entries()] == PROJECTS


def test_the_projects_cover_every_database_and_version(registry: Registry) -> None:
    covered = {
        (m.datasource.db_type, m.datasource.db_version) for m in registry.all_entries()
    }

    assert covered == {
        ("oracle", "19c"),
        ("oracle", "12c"),
        ("oracle", "11g"),
        ("postgresql", "14"),
        ("postgresql", "16"),
    }


def test_there_is_one_profile_one_examples_file_and_no_example_in_semantic() -> None:
    assert [p.name for p in (REPO_ROOT / "profiles").iterdir()] == ["innoproduct"]
    # 제품 공통 파일 하나와 테이블당 파일 하나
    product_dir = REPO_ROOT / "profiles" / "innoproduct"
    assert sorted(p.name for p in product_dir.iterdir()) == ["product.yml", "tables"]
    assert sorted(p.stem for p in (product_dir / "tables").glob("*.yml")) == sorted(
        EXPECTED_COLUMNS
    )
    assert [p.name for p in (REPO_ROOT / "examples").iterdir()] == ["innoproduct.yml"]
    for path in (REPO_ROOT / "semantic").glob("*.json"):
        assert "examples" not in path.read_text(encoding="utf-8"), path.name


# ---- profile: 실제 테이블 단위 ----


def test_the_profile_is_organized_by_real_tables_with_the_documented_columns(
    registry: Registry,
) -> None:
    metadata = project(registry, "p001")

    assert [t.name for t in metadata.tables] == sorted(EXPECTED_COLUMNS)
    for table in metadata.tables:
        assert [c.name for c in table.columns] == EXPECTED_COLUMNS[table.name], (
            table.name
        )


def test_every_column_is_described_once_and_has_a_type(registry: Registry) -> None:
    for table in project(registry, "p001").tables:
        assert table.description, table.name
        for column in table.columns:
            assert column.type in {"number", "string"}, (table.name, column.name)
            assert column.description, (table.name, column.name)


def test_the_documented_join_keys_are_in_the_profile(registry: Registry) -> None:
    text = "\n".join(item.render() for item in project(registry, "p001").relationships)

    for key in (
        "OBJ_INV.SID = OBJ_MAIN.SID",
        "OBJ_INV.SUBSID = OBJ_MAIN.SID",
        "OBJ_INV.PROP_SID = OBJ_MAIN.SID",
        "OBJ_INV.INV_TYPE = OBJINV_TYPE.INV_TYPE",
    ):
        assert key in text


def test_all_projects_share_one_table_structure(registry: Registry) -> None:
    structures = {
        str([(t.name, [c.name for c in t.columns]) for t in m.tables])
        for m in registry.all_entries()
    }

    assert len(structures) == 1  # 같은 profile을 쓰므로 테이블 구조는 모두 같다


def test_the_profile_does_not_mix_in_views_or_per_project_values(
    registry: Registry,
) -> None:
    raw = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPO_ROOT / "profiles" / "innoproduct").rglob("*.yml"))
    )

    assert "views:" not in raw
    assert "definition:" not in raw
    assert "source:" not in raw
    assert "examples:" not in raw
    assert "code_catalog" not in raw
    assert "table_data" not in raw


# ---- semantic: 프로젝트마다 다른 테이블 데이터(행) ----


def test_the_same_code_has_a_different_name_in_each_project(registry: Registry) -> None:
    names = {pid: type_names(project(registry, pid)) for pid in PROJECTS}

    # 101, 102는 여러 프로젝트가 같은 코드로 쓰지만 이름은 모두 다르다
    for code in ("101", "102"):
        used = [(pid, n[code]) for pid, n in names.items() if code in n]
        assert len(used) >= 4, code
        assert len({name for _, name in used}) == len(used), (code, used)
    assert names["p001"] == {"101": "장기상품", "102": "일반상품"}
    assert names["p002"]["101"] == "정기보험"
    assert names["p003"]["101"] == "연금상품"
    assert names["p005"]["101"] == "단체상품"


def test_some_codes_exist_in_only_one_project(registry: Registry) -> None:
    assert "111" in type_names(project(registry, "p002"))
    assert "121" in type_names(project(registry, "p003"))
    for other in ("p001", "p003", "p005"):
        assert "111" not in type_names(project(registry, other))


def test_the_same_item_code_can_also_have_different_names(registry: Registry) -> None:
    def item(pid: str) -> str:
        return item_names(project(registry, pid)).get("#S00000031", "")

    assert (item("p001"), item("p003"), item("p005")) == (
        "보장기간",
        "연금개시연령",
        "보장기간",
    )


def test_one_project_keeps_the_rows_of_different_tables_apart(
    registry: Registry,
) -> None:
    p005 = project(registry, "p005")

    assert type_names(p005) == {"101": "단체상품", "102": "개인상품"}
    assert item_names(p005)["#S00000001"] == "납입주기"
    # 관계 종류의 이름은 OBJINV_TYPE의 행(INV_TYPE, TYPE_GBN, TYPE_NAME이 한 행)에 있다
    kinds = {
        row["INV_TYPE"]: (row["TYPE_GBN"], row["TYPE_NAME"])
        for row in p005.table_data["OBJINV_TYPE"]
    }
    assert kinds == {"11": ("1", "기본 상품구조"), "41": ("4", "필수 관계규칙")}
    assert "101" not in kinds
    assert "OBJ_INV" not in p005.table_data  # 이름은 OBJ_INV에 붙이지 않는다


def test_a_sample_row_keeps_every_column_of_the_row_together(
    registry: Registry,
) -> None:
    rows = project(registry, "p001").table_data["OBJ_MAIN"]

    # 유형 행: 항목코드(R10_1)는 값이 없어 ""이고, 항목 행: TYPEID는 0이고 항목코드가 있다
    assert rows[0] == {
        "SID": "1001",
        "BIZCODE": "TYPE101",
        "TYPEID": "101",
        "R10_1": "",
        "OBJ_NAME": "장기상품",
        "VF_DT": "20200101",
        "VT_DT": "99991231",
    }
    assert rows[-1] == {
        "SID": "2001",
        "BIZCODE": "ITEM0031",
        "TYPEID": "0",
        "R10_1": "#S00000031",
        "OBJ_NAME": "보장기간",
        "VF_DT": "20200101",
        "VT_DT": "99991231",
    }


@pytest.mark.parametrize("project_id", PROJECTS)
def test_every_sample_row_has_every_column_of_its_table_and_no_null(
    registry: Registry, project_id: str
) -> None:
    metadata = project(registry, project_id)

    for table_name, row in iter_rows(metadata.table_data):
        table = metadata.get_table(table_name)
        assert table is not None
        # 테이블 정의의 컬럼을 하나도 빠뜨리지 않고, 정의 순서대로 적는다
        assert list(row) == [column.name for column in table.columns], table_name
        assert all(isinstance(value, str) for value in row.values()), table_name


def test_rows_with_a_missing_value_use_an_empty_string_never_null() -> None:
    for path in sorted((REPO_ROOT / "semantic").glob("*.json")):
        assert "null" not in path.read_text(encoding="utf-8"), path.name


def test_the_dummy_projects_cover_every_kind_of_semantic_file(
    registry: Registry,
) -> None:
    assert project(registry, "p001").table_data
    assert (REPO_ROOT / "semantic" / "p004.json").read_text(
        encoding="utf-8"
    ).strip() == "{}"
    assert project(registry, "p004").table_data == {}  # 파일은 있지만 비어 있다
    assert not (REPO_ROOT / "semantic" / "p006.json").exists()  # 파일 자체가 없다
    assert project(registry, "p006").table_data == {}
    p005 = project(registry, "p005").table_data
    assert list(p005) == [
        "OBJ_MAIN",
        "OBJINV_TYPE",
    ]  # 테이블 키 아래에 그 테이블의 행들이 모인다
    assert len(list(iter_rows(p005))) == 7


# ---- 공통 예시 ----


def test_every_project_gets_the_same_common_examples(registry: Registry) -> None:
    first = project(registry, "p001").examples

    assert len(first) == 7
    for pid in PROJECTS:
        assert project(registry, pid).examples == first


def test_the_common_examples_use_codes_but_never_a_projects_code_names(
    registry: Registry,
) -> None:
    raw = (REPO_ROOT / "examples" / "innoproduct.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    text = "\n".join(e["question"] + " " + e["sql"] for e in parsed["examples"])

    assert "TYPEID = 101" in text  # 코드는 써도 된다
    # 프로젝트마다 다른 "이름" 컬럼의 값 (코드나 날짜가 아니라 이름)
    all_names = {
        value
        for pid in PROJECTS
        for _, row in iter_rows(project(registry, pid).table_data)
        for column in ("OBJ_NAME", "TYPE_NAME")
        if (value := row.get(column))
    }
    for name in all_names:
        assert name not in text, name  # 이름은 프로젝트마다 달라서 쓰지 않는다


@pytest.mark.parametrize("project_id", PROJECTS)
def test_every_common_example_works_for_each_projects_own_database(
    registry: Registry, project_id: str
) -> None:
    metadata = project(registry, project_id)
    adapter = get_adapter(metadata.datasource.db_type, metadata.datasource.db_version)

    for example in metadata.examples:
        assert check_example(example.sql, metadata, adapter) == [], (
            project_id,
            example.question,
        )


def test_the_examples_cover_the_documented_query_patterns(registry: Registry) -> None:
    sql = "\n".join(e.sql for e in project(registry, "p001").examples)

    assert "R10_1 = '#S00000031'" in sql  # 허용값 조회
    assert "TYPEID <> 0" in sql  # 상품 객체 조회
    assert "T4.TYPE_GBN = 1" in sql  # 상품 구조
    assert "T4.TYPE_GBN = 4" in sql  # 관계규칙
    assert "ORDER BY T4.TYPE_NAME, T2.SET_SEQ" in sql
    assert "VF_DT <= '20240101' AND VT_DT >= '20240101'" in sql  # 기준일자 비교
    assert "SYSDATE" not in sql and "CURRENT_DATE" not in sql  # 날짜 함수는 쓰지 않는다


# ---- 프롬프트 ----


@pytest.mark.parametrize("project_id", PROJECTS)
def test_every_prompt_shows_real_names_and_the_projects_own_codes(
    registry: Registry, project_id: str
) -> None:
    metadata = project(registry, project_id)

    text = system_prompt(metadata)

    for table, columns in EXPECTED_COLUMNS.items():
        assert f"{table}: " in text
        for column in columns:
            assert f"  - {column} (" in text
    for table_name, row in iter_rows(metadata.table_data):
        table = metadata.get_table(table_name)
        assert (
            table is not None and table.name_column is not None
        )  # 샘플은 이름 컬럼이 있다
        name = row[table.name_column]
        assert name and f"- {name}: " in text, (table_name, row)
        line = next(
            item for item in text.splitlines() if item.startswith(f"- {name}: ")
        )
        keys = {key.upper() for key in table.key_columns}
        for column, value in row.items():
            if column.upper() in keys and value:
                assert f"{column} = " in line and value in line, (name, column)
            else:
                # 조건으로 쓰지 않는 컬럼(SID, 날짜, 이름 컬럼)은 그 줄에 나오지 않는다
                assert f"{column} =" not in line, (name, column)
    # 테이블 전용 규칙은 그 테이블 아래에 나온다
    for table in metadata.tables:
        for rule in table.rules:
            assert f"  [규칙] {rule}" in text
    # 제품 용어 '서비스뷰'는 있어도 되지만, 서버 안의 뷰 개념은 프롬프트에 나오지 않는다
    for gone in ("definition", "v_object", "valid_now", "{{", "source"):
        assert gone not in text, gone


def test_codes_of_one_project_never_appear_in_the_prompt_of_another(
    registry: Registry,
) -> None:
    prompts = {pid: system_prompt(project(registry, pid)) for pid in PROJECTS}

    assert lookup_text("정기보험", "TYPEID = 101") in prompts["p002"]
    assert "정기보험" not in prompts["p001"]
    assert lookup_text("장기상품", "TYPEID = 101") in prompts["p001"]
    assert "장기상품" not in prompts["p002"]
    assert lookup_text("특약", "TYPEID = 111") in prompts["p002"]
    assert "특약" not in prompts["p001"]
    assert (
        lookup_text("납입주기", "TYPEID = 0 AND R10_1 = '#S00000001'")
        in prompts["p005"]
    )
    assert "납입주기" not in prompts["p001"]
    assert (
        lookup_text("보장기간", "TYPEID = 0 AND R10_1 = '#S00000031'")
        in prompts["p001"]
    )
    assert (
        lookup_text("연금개시연령", "TYPEID = 0 AND R10_1 = '#S00000031'")
        in prompts["p003"]
    )
    assert "연금개시연령" not in prompts["p001"]
    # 관계 종류의 이름은 OBJINV_TYPE의 행에서 온다
    assert (
        lookup_text(
            "기본 상품구조", "INV_TYPE = 11 AND TYPE_GBN = 1 AND END_DT = '99991231'"
        )
        in prompts["p005"]
    )
    heading = "테이블 데이터 (실제 행에서 뽑은 것."  # 데이터가 없는 프로젝트에는 이 목록이 없다
    assert heading in prompts["p001"]
    assert heading not in prompts["p004"] and heading not in prompts["p006"]
    # 없는 데이터를 찾으라는 안내도 나오지 않는다
    lookup = "질문에 위 이름이 나오면"
    assert lookup in prompts["p001"]
    assert lookup not in prompts["p004"] and lookup not in prompts["p006"]


def test_the_prompt_dialect_rules_follow_each_projects_database(
    registry: Registry,
) -> None:
    prompts = {pid: system_prompt(project(registry, pid)) for pid in PROJECTS}

    assert "FETCH FIRST N ROWS ONLY를 사용합니다" in prompts["p004"]  # Oracle 12c
    assert "FETCH FIRST를 쓸 수 없습니다" in prompts["p003"]  # Oracle 11g
    assert "LIMIT N" in prompts["p002"] and "LIMIT N" in prompts["p005"]  # PostgreSQL
    assert "Oracle" not in prompts["p002"]
    assert "SYSDATE" in prompts["p001"] and "CURRENT_DATE" in prompts["p002"]


def test_the_usage_rules_sit_on_the_tables_they_belong_to(registry: Registry) -> None:
    metadata = project(registry, "p001")

    def rules(table: str) -> str:
        found = metadata.get_table(table)
        assert found is not None
        return "\n".join(found.rules)

    for rule in ("TYPEID <> 0", "R10_1", "BIZCODE를 함께 조회"):
        assert rule in rules("OBJ_MAIN"), rule
    for rule in ("TYPE_GBN", "SET_SEQ", "INV_TYPE"):
        assert rule in rules("OBJ_INV"), rule
    assert "END_DT = '99991231'" in rules("OBJINV_TYPE")


def test_the_glossary_keeps_only_rules_that_span_tables(registry: Registry) -> None:
    glossary = "\n".join(project(registry, "p001").glossary)

    assert "VF_DT <= 기준일자 AND VT_DT >= 기준일자" in glossary
    assert "현재" in glossary
    # 한 테이블에만 해당하는 규칙은 테이블로 옮겼다
    for moved in ("TYPEID <> 0", "SET_SEQ", "END_DT = '99991231'", "BIZCODE"):
        assert moved not in glossary, moved


def test_every_project_has_its_own_metadata_version(registry: Registry) -> None:
    versions = [m.metadata_version for m in registry.all_entries()]

    assert len(set(versions)) == len(versions)
    assert all(re.fullmatch(r"[0-9a-f]{12}", v) for v in versions)


def test_the_sample_tables_name_the_column_that_holds_a_rows_name(
    registry: Registry,
) -> None:
    metadata = project(registry, "p001")

    main = metadata.get_table("OBJ_MAIN")
    kinds = metadata.get_table("OBJINV_TYPE")
    assert main is not None and kinds is not None
    assert main.name_column == "OBJ_NAME"
    assert kinds.name_column == "TYPE_NAME"
    # 조회 조건으로 쓰는 컬럼만 지정한다 (SID, 날짜 같은 컬럼은 행에는 있어도 조건으로 쓰지 않는다)
    assert main.key_columns == ("TYPEID", "R10_1")
    assert kinds.key_columns == ("INV_TYPE", "TYPE_GBN", "END_DT")
    assert metadata.get_table("OBJ_INV").name_column is None  # type: ignore[union-attr]
