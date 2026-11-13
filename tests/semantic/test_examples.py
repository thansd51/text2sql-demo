"""examples/<제품>.yml: 제품을 쓰는 모든 프로젝트가 함께 쓰는 질문-SQL 예시."""

import re
from pathlib import Path

import pytest

from tests.semantic.helpers import (
    DATASOURCE,
    EXAMPLES_YAML,
    PRODUCT_YAML,
    PROFILE_FILES,
    make_dirs,
)
from text2sql.semantic import MetadataError, build_registry

HANGUL = re.compile(r"[가-힣]")


def problems_of(info: pytest.ExceptionInfo[MetadataError]) -> str:
    return "\n".join(info.value.problems)


def test_the_examples_file_is_optional(tmp_path: Path) -> None:
    metadata = build_registry(make_dirs(tmp_path).repository()).get("p001")

    assert metadata is not None
    assert metadata.examples == ()


def test_every_project_that_uses_the_product_gets_the_same_examples(
    tmp_path: Path,
) -> None:
    dirs = make_dirs(
        tmp_path,
        datasources={
            "p001": DATASOURCE,
            "p002": {
                **DATASOURCE,
                "id": "p002",
                "db_type": "postgresql",
                "db_version": "14",
            },
        },
        semantics={},
        examples={"innoproduct": EXAMPLES_YAML},
    )

    registry = build_registry(dirs.repository())

    assert registry.get("p001").examples == registry.get("p002").examples  # type: ignore[union-attr]
    assert len(registry.get("p001").examples) == 2  # type: ignore[union-attr]


def test_examples_are_read_through_the_repository_interface(tmp_path: Path) -> None:
    repository = make_dirs(
        tmp_path, examples={"innoproduct": EXAMPLES_YAML}
    ).repository()

    assert [e.question for e in repository.get_examples("innoproduct")] == [
        "오브젝트 이름 목록",
        "유형코드가 101인 오브젝트의 코드와 이름",
    ]
    assert repository.get_examples("unknown") == ()


def test_an_examples_file_with_a_different_product_name_is_rejected(
    tmp_path: Path,
) -> None:
    dirs = make_dirs(tmp_path, examples={"other": EXAMPLES_YAML})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "examples/other.yml: product: 파일명(other)과 product(innoproduct)가 다릅니다"
        in problems_of(info)
    )


def test_an_examples_file_without_a_matching_profile_is_rejected(
    tmp_path: Path,
) -> None:
    orphan = EXAMPLES_YAML.replace("product: innoproduct", "product: ghost")
    dirs = make_dirs(tmp_path, examples={"ghost": orphan})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "examples/ghost.yml: 대응하는 profiles/ghost/ 디렉터리가 없습니다"
        in problems_of(info)
    )


@pytest.mark.parametrize(
    ("broken", "expected"),
    [
        (
            "product: innoproduct\nexamples:\n  - question: 질문만\n",
            "examples[0].sql: 필수 항목이 없습니다",
        ),
        (
            "product: innoproduct\nexamples:\n  - sql: SELECT 1 FROM T\n",
            "examples[0].question: 필수 항목이 없습니다",
        ),
        (
            "product: innoproduct\nexamples:\n  - question: ''\n    sql: SELECT 1 FROM T\n",
            "examples[0].question: 비어 있을 수 없습니다",
        ),
        ("examples: []\n", "product: 필수 항목이 없습니다"),
        ("product: innoproduct\nexample: []\n", "example: 알 수 없는 항목입니다"),
    ],
)
def test_malformed_examples_are_reported_with_file_and_location(
    tmp_path: Path, broken: str, expected: str
) -> None:
    dirs = make_dirs(tmp_path, examples={"innoproduct": broken})

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert f"examples/innoproduct.yml: {expected}" in problems_of(info)
    assert HANGUL.search(problems_of(info))


def test_invalid_yaml_in_the_examples_file_is_reported(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path, examples={"innoproduct": "product: innoproduct\nexamples: [\n"}
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert re.search(
        r"examples/innoproduct\.yml: \d+행 \d+열: YAML 문법이 올바르지 않습니다",
        problems_of(info),
    )


def test_a_missing_examples_directory_is_fine(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path)
    dirs.examples.rmdir()

    assert build_registry(dirs.repository()).get("p001").examples == ()  # type: ignore[union-attr]


def test_the_profile_no_longer_carries_examples(tmp_path: Path) -> None:
    dirs = make_dirs(
        tmp_path,
        profiles={
            "innoproduct": {
                **PROFILE_FILES,
                "product.yml": PRODUCT_YAML
                + "examples:\n  - question: q\n    sql: SELECT 1 FROM T\n",
            }
        },
    )

    with pytest.raises(MetadataError) as info:
        dirs.repository()

    assert (
        "profiles/innoproduct/product.yml: examples: 알 수 없는 항목입니다"
        in problems_of(info)
    )
