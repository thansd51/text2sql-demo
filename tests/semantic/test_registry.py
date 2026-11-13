import re
from pathlib import Path

import pytest

from tests.semantic.helpers import (
    DATASOURCE,
    EXAMPLES_YAML,
    OBJ_MAIN_YAML,
    PROFILE_FILES,
    SEMANTIC,
    make_dirs,
)
from text2sql.semantic import (
    DataSource,
    Example,
    MetadataError,
    Profile,
    Semantic,
    SemanticRepository,
    build_registry,
)

HANGUL = re.compile(r"[가-힣]")
SRC = Path(__file__).resolve().parents[2] / "src" / "text2sql" / "semantic"


def other_profile(product: str, table: str) -> dict[str, str]:
    """다른 제품의 profile 파일들 (product.yml과 테이블 파일 하나)."""
    return {
        "product.yml": f"""\
product: {product}
glossary:
  - {product} 용어
relationships:
  - from: {table}.ID
    to: {table}.ID
    note: {product}의 키
""",
        f"tables/{table}.yml": f"""\
name: {table}
description: 다른 제품의 테이블
columns:
  - name: ID
    type: number
""",
    }


def other_examples(product: str, table: str) -> str:
    return f"""\
product: {product}
examples:
  - question: {product} 예시
    sql: SELECT ID FROM {table}
"""


# ---- 중복 테이블 이름 ----


def test_table_names_are_compared_ignoring_case(tmp_path: Path) -> None:
    # 파일 이름은 달라도(obj_main.yml) 테이블 이름이 대소문자만 다르면 중복이다
    lower = OBJ_MAIN_YAML.replace("name: OBJ_MAIN", "name: obj_main")
    dirs = make_dirs(
        tmp_path,
        profiles={"innoproduct": {**PROFILE_FILES, "tables/obj_main.yml": lower}},
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "profiles/innoproduct/: tables: 테이블 이름이(가) 중복됩니다: OBJ_MAIN"
        in "\n".join(info.value.problems)
    )


def test_duplicate_table_names_across_profiles_fail_at_startup(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        datasources={"p001": {**DATASOURCE, "profiles": ["innoproduct", "second"]}},
        profiles={
            "innoproduct": PROFILE_FILES,
            "second": other_profile("second", "OBJ_MAIN"),
        },
    )

    with pytest.raises(MetadataError) as info:
        build_registry(dirs.repository())

    text = "\n".join(info.value.problems)
    assert "datasources/p001.json" in text
    assert "테이블 이름 'OBJ_MAIN'" in text
    assert "'innoproduct'" in text
    assert "'second'(profiles/second/)" in text


def test_same_table_name_in_profiles_not_used_together_is_fine(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        datasources={
            "p001": DATASOURCE,
            "p002": {**DATASOURCE, "id": "p002", "profiles": ["second"]},
        },
        semantics={},
        profiles={
            "innoproduct": PROFILE_FILES,
            "second": other_profile("second", "OBJ_MAIN"),
        },
    )

    registry = build_registry(dirs.repository())

    first = registry.get("p001")
    second = registry.get("p002")
    assert first is not None
    assert second is not None
    main = first.get_table("OBJ_MAIN")
    assert main is not None
    assert [c.name for c in main.columns][:2] == ["SID", "BIZCODE"]
    assert [c.name for c in second.tables[0].columns] == ["ID"]


# ---- 여러 제품 병합 ----


def test_multiple_profiles_are_merged_in_listed_order(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        datasources={"p001": {**DATASOURCE, "profiles": ["second", "innoproduct"]}},
        profiles={
            "innoproduct": PROFILE_FILES,
            "second": other_profile("second", "OTHER_TABLE"),
        },
        examples={
            "innoproduct": EXAMPLES_YAML,
            "second": other_examples("second", "OTHER_TABLE"),
        },
    )

    metadata = build_registry(dirs.repository()).get("p001")

    assert metadata is not None
    # 제품은 나열한 순서, 한 제품 안의 테이블은 파일 이름순이다
    assert [t.name for t in metadata.tables] == ["OTHER_TABLE", "OBJ_INV", "OBJ_MAIN"]
    assert metadata.table_names() == {"OTHER_TABLE", "OBJ_MAIN", "OBJ_INV"}
    assert metadata.glossary == (
        "second 용어",
        "오브젝트명은 중복될 수 있다",
    )
    assert (
        metadata.relationships[0].render()
        == "OTHER_TABLE.ID = OTHER_TABLE.ID (second의 키)"
    )
    assert [e.question for e in metadata.examples] == [
        "second 예시",
        "오브젝트 이름 목록",
        "유형코드가 101인 오브젝트의 코드와 이름",
    ]
    assert set(metadata.columns_by_table()) == {"OTHER_TABLE", "OBJ_MAIN", "OBJ_INV"}


def test_get_table_ignores_case(tmp_path: Path) -> None:
    metadata = build_registry(make_dirs(tmp_path).repository()).get("p001")

    assert metadata is not None
    assert metadata.get_table("obj_main") is metadata.get_table("OBJ_MAIN")
    assert metadata.get_table("NOPE") is None


# ---- metadata_version (파일 내용 해시) ----


def version(tmp_path: Path, **kwargs: object) -> str:
    dirs = make_dirs(tmp_path, **kwargs)  # type: ignore[arg-type]
    return dirs.repository().content_hash("p001")


def test_hash_is_stable_for_same_content(tmp_path: Path) -> None:
    assert version(tmp_path / "a") == version(tmp_path / "b")


@pytest.mark.parametrize(
    "change",
    [
        {"datasources": {"p001": {**DATASOURCE, "db_version": "12c"}}},
        {
            "semantics": {
                "p001": {"OBJ_MAIN": [{"TYPEID": "999", "OBJ_NAME": "다른 이름"}]}
            }
        },
        {"semantics": {}},
        {
            "profiles": {
                "innoproduct": {
                    **PROFILE_FILES,
                    "tables/OBJ_MAIN.yml": OBJ_MAIN_YAML + "# 주석 한 줄\n",
                }
            }
        },
        {  # 테이블 파일을 하나 더하면 달라진다
            "profiles": {
                "innoproduct": {
                    **PROFILE_FILES,
                    "tables/EXTRA.yml": "name: EXTRA\ncolumns:\n  - name: A\n    type: string\n",
                }
            }
        },
        {  # 제품 공통 파일이 바뀌어도 달라진다
            "profiles": {
                "innoproduct": {
                    **PROFILE_FILES,
                    "product.yml": PROFILE_FILES["product.yml"] + "# 주석\n",
                }
            }
        },
        {"examples": {"innoproduct": EXAMPLES_YAML}},
    ],
)
def test_hash_changes_when_any_source_file_changes(
    tmp_path: Path, change: dict[str, object]
) -> None:
    assert version(tmp_path / "base") != version(tmp_path / "changed", **change)


def test_hash_changes_when_the_common_examples_change(tmp_path: Path) -> None:
    first = version(tmp_path / "a", examples={"innoproduct": EXAMPLES_YAML})
    second = version(
        tmp_path / "b",
        examples={
            "innoproduct": EXAMPLES_YAML
            + "  - question: 하나 더\n    sql: SELECT SID FROM OBJ_MAIN\n"
        },
    )

    assert first != second


def test_hash_ignores_other_datasources(tmp_path: Path) -> None:
    base = make_dirs(tmp_path / "base", datasources={"p001": DATASOURCE}, semantics={})
    extended = make_dirs(
        tmp_path / "ext",
        datasources={"p001": DATASOURCE, "p002": {**DATASOURCE, "id": "p002"}},
        semantics={"p002": SEMANTIC},
    )

    assert base.repository().content_hash("p001") == extended.repository().content_hash(
        "p001"
    )
    assert extended.repository().content_hash(
        "p001"
    ) != extended.repository().content_hash("p002")


def test_hash_is_same_for_crlf_and_bom(tmp_path: Path) -> None:
    plain = make_dirs(tmp_path / "plain", examples={"innoproduct": EXAMPLES_YAML})
    other = make_dirs(tmp_path / "other", examples={"innoproduct": EXAMPLES_YAML})
    for directory, suffix in (
        (other.datasources, ".json"),
        (other.profiles, ".yml"),
        (other.semantic, ".json"),
        (other.examples, ".yml"),
    ):
        for path in directory.rglob(f"*{suffix}"):
            text = path.read_bytes().decode("utf-8")
            path.write_bytes(
                b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")
            )

    assert other.repository().content_hash("p001") == plain.repository().content_hash(
        "p001"
    )


def test_registry_uses_the_content_hash_as_metadata_version(tmp_path: Path) -> None:
    repository = make_dirs(tmp_path).repository()

    metadata = build_registry(repository).get("p001")

    assert metadata is not None
    assert metadata.metadata_version == repository.content_hash("p001")


def test_content_hash_of_unknown_datasource_raises(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        make_dirs(tmp_path).repository().content_hash("nope")


# ---- 인터페이스 ----


class InMemoryRepository:
    """파일 없이 인터페이스만 구현한다. 레지스트리가 인터페이스에만 의존함을 보인다."""

    def __init__(self) -> None:
        self.datasource = DataSource(
            id="mem",
            name="메모리",
            db_type="postgresql",
            db_version="14",
            profiles=("p",),
        )
        self.profile = Profile.model_validate(
            {
                "product": "p",
                "tables": [
                    {
                        "name": "TBL_A",
                        "columns": [{"name": "A", "type": "string"}],
                    }
                ],
            }
        )

    def get_datasource(self, datasource_id: str) -> DataSource | None:
        return self.datasource if datasource_id == "mem" else None

    def list_datasources(self) -> list[DataSource]:
        return [self.datasource]

    def get_semantic(self, datasource_id: str) -> Semantic:
        return Semantic({"TBL_A": [{"A": "메모리 값"}]})

    def get_profile(self, product: str) -> Profile | None:
        return self.profile if product == "p" else None

    def get_examples(self, product: str) -> tuple[Example, ...]:
        return (Example(question="메모리 예시", sql="SELECT A FROM TBL_A"),)

    def content_hash(self, datasource_id: str) -> str:
        return "memory-0001"


def test_registry_depends_only_on_the_repository_interface() -> None:
    repository: SemanticRepository = InMemoryRepository()

    metadata = build_registry(repository).get("mem")

    assert metadata is not None
    assert metadata.table_names() == {"TBL_A"}
    assert metadata.table_data == {"TBL_A": ({"A": "메모리 값"},)}
    assert [e.question for e in metadata.examples] == ["메모리 예시"]
    assert metadata.metadata_version == "memory-0001"


def test_missing_profile_in_a_foreign_repository_is_reported() -> None:
    class RepositoryWithoutProfiles(InMemoryRepository):
        def get_profile(self, product: str) -> Profile | None:
            return None

    with pytest.raises(MetadataError) as info:
        build_registry(RepositoryWithoutProfiles())

    assert (
        "profiles[0]: 제품 'p'에 해당하는 profiles/p/ 디렉터리가 없습니다"
        in "\n".join(info.value.problems)
    )


# ---- 의존 방향 ----


def test_semantic_package_does_not_import_other_concepts() -> None:
    forbidden = re.compile(
        r"^\s*(from|import)\s+text2sql\.(api|pipeline|validation|dialects|llm)\b",
        re.MULTILINE,
    )

    for path in SRC.glob("*.py"):
        assert not forbidden.search(path.read_text(encoding="utf-8")), path.name
