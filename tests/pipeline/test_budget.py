"""프롬프트 크기 관리: 예산을 넘으면 질문과 관련 있는 테이블만 프롬프트에 넣는다.

테이블이 수십 개로 늘어도 컨텍스트가 작은 모델에서 규칙이 잘리지 않게 하려는 것이다.
"""

import logging

import pytest

from tests.fakes import FakeLLM
from tests.pipeline.conftest import MAX_ROWS, MetadataFactory
from text2sql.config import Settings
from text2sql.dialects import get_adapter
from text2sql.pipeline import (
    PromptTooLargeError,
    SqlGenerator,
    Status,
    check_prompt_budget,
    estimate_tokens,
    fit_metadata,
    prompt_budget_tokens,
    score_tables,
)
from text2sql.pipeline.prompt import build_system_prompt
from text2sql.pipeline.references import extract_table_names
from text2sql.semantic import MetadataError, ProjectMetadata
from text2sql.startup import load_registry

COUNT = 12


def table_yaml(index: int) -> str:
    return f"""\
name: T{index:02d}
description: 시험용 테이블 {index}
group: 영역{index % 3}
columns:
  - name: ID
    type: number
    description: 식별자
  - name: LABEL
    type: string
    description: 이름 모양의 값
    synonyms: [별칭{index:02d}z]
"""


def profile_files(count: int = COUNT) -> dict[str, str]:
    relationships = "\n".join(
        f"  - from: T{i:02d}.ID\n    to: T{i + 1:02d}.ID\n    note: 다음 테이블"
        for i in (5,)
    )
    files = {
        "product.yml": f"product: innoproduct\nrelationships:\n{relationships}\n",
    }
    for index in range(count):
        files[f"tables/T{index:02d}.yml"] = table_yaml(index)
    return files


EXAMPLES = """\
product: innoproduct
examples:
  - question: T00 목록
    sql: SELECT LABEL FROM T00
  - question: T05 목록
    sql: SELECT LABEL FROM T05
  - question: T05와 T00 조인
    sql: SELECT A.LABEL FROM T05 A JOIN T00 B ON A.ID = B.ID
"""

# 프로젝트 데이터: 테이블 -> 행 목록 (행 하나에 컬럼 여러 개)
CODES = {
    "T00": [{"ID": "1", "LABEL": "영공공"}],
    "T05": [{"ID": "2", "LABEL": "오오오"}],
    "T07": [{"ID": "3", "LABEL": "칠칠칠"}],
}


@pytest.fixture
def many(make_metadata: MetadataFactory) -> ProjectMetadata:
    return make_metadata(profile=profile_files(), semantic=CODES, examples=EXAMPLES)


def rules_of(metadata: ProjectMetadata) -> str:
    return get_adapter(
        metadata.datasource.db_type, metadata.datasource.db_version
    ).prompt_rules()


def cost_of(metadata: ProjectMetadata, question: str = "질문") -> int:
    text = build_system_prompt(metadata, rules_of(metadata)) + "질문: " + question
    return estimate_tokens(text)


def fit(metadata: ProjectMetadata, question: str, budget: int):
    return fit_metadata(
        metadata, rules_of(metadata), question, budget, dialect="oracle"
    )


def small_budget(metadata: ProjectMetadata, tables: int) -> int:
    """테이블이 대략 `tables`개 들어가는 예산 (예시 몫 포함)."""
    from text2sql.pipeline.budget import _reduce

    base = cost_of(_reduce(metadata, (), ()))
    one = cost_of(_reduce(metadata, ("T00",), ())) - base
    return int(base + one * tables / 0.7)


# ---- 어림 ----


def test_token_estimate_rounds_up_and_uses_the_given_ratio() -> None:
    assert estimate_tokens("가" * 18) == 10  # 1.8자 = 1토큰
    assert estimate_tokens("가" * 19) == 11  # 올림
    assert estimate_tokens("가" * 10, chars_per_token=1.0) == 10
    assert estimate_tokens("") == 0


def test_the_prompt_budget_leaves_room_for_the_answer_and_a_retry() -> None:
    budget = prompt_budget_tokens(16384, 512)

    assert budget < 16384 - 512  # 재시도 여유를 더 뺀다
    assert budget > 0


# ---- 예산 안이면 그대로 ----


def test_nothing_is_cut_when_the_prompt_fits(many: ProjectMetadata) -> None:
    result = fit(many, "질문", 10**6)

    assert result.metadata is many
    assert not result.reduced
    assert len(result.selected_tables) == COUNT


# ---- 예산을 넘으면 줄인다 ----


def test_over_budget_keeps_the_tables_the_question_points_at(
    many: ProjectMetadata,
) -> None:
    budget = small_budget(many, 3)
    assert cost_of(many) > budget

    result = fit(many, "별칭09z 값을 보여줘", budget)

    assert result.reduced
    assert "T09" in result.selected_tables
    assert len(result.selected_tables) < COUNT
    assert cost_of(result.metadata, "별칭09z 값을 보여줘") <= budget
    assert result.estimated_tokens <= budget


def test_unrelated_tables_are_left_out(many: ProjectMetadata) -> None:
    result = fit(many, "별칭09z 값을 보여줘", small_budget(many, 3))

    assert "T00" not in result.selected_tables
    assert "T11" not in result.selected_tables


def test_the_kept_tables_stay_in_their_original_order(many: ProjectMetadata) -> None:
    result = fit(many, "별칭09z와 별칭02z", small_budget(many, 4))

    names = [t.name for t in result.metadata.tables]
    original = [t.name for t in many.tables]
    assert names == [n for n in original if n in names]
    assert {"T02", "T09"} <= set(names)


def test_tables_joined_to_a_chosen_table_come_along(many: ProjectMetadata) -> None:
    # T05는 T06과 조인 키가 있다. 질문은 T05만 가리켜도 T06을 함께 담는다.
    result = fit(many, "별칭05z", small_budget(many, 3))

    assert {"T05", "T06"} <= set(result.selected_tables)


def test_relationships_data_and_examples_follow_the_kept_tables(
    many: ProjectMetadata,
) -> None:
    result = fit(many, "별칭05z", small_budget(many, 3))
    kept = result.metadata

    assert {t.name for t in kept.tables} >= {"T05", "T06"}
    assert [r.render() for r in kept.relationships] == ["T05.ID = T06.ID (다음 테이블)"]
    # 테이블 데이터는 남은 테이블 것만
    assert list(kept.table_data) == ["T05"]
    # 남지 않은 테이블을 쓰는 예시는 빠진다 (T00, 그리고 T00와 조인하는 예시)
    assert [e.question for e in kept.examples] == ["T05 목록"]
    # 전역 값은 그대로다
    assert kept.glossary == many.glossary
    assert kept.datasource == many.datasource


def test_a_value_from_the_table_data_in_the_question_points_at_its_table(
    many: ProjectMetadata,
) -> None:
    scores = score_tables(many, "칠칠칠 목록")

    assert scores["T07"] > 0
    assert scores["T07"] == max(scores.values())


def test_scores_use_table_name_synonyms_and_description_words(
    many: ProjectMetadata,
) -> None:
    assert score_tables(many, "t03 보여줘")["T03"] > score_tables(many, "보여줘")["T03"]
    assert score_tables(many, "별칭04z")["T04"] > 0
    assert score_tables(many, "시험용 테이블")["T01"] > 0  # 설명의 단어
    assert not any(score_tables(many, "전혀 상관 없는 말").values())


def test_without_any_clue_the_first_tables_fill_the_budget(
    many: ProjectMetadata,
) -> None:
    result = fit(many, "전혀 상관 없는 말", small_budget(many, 3))

    names = list(result.selected_tables)
    assert result.reduced
    assert names[0] == "T00"
    assert names == [t.name for t in many.tables][: len(names)]


def test_the_same_input_gives_the_same_result(many: ProjectMetadata) -> None:
    budget = small_budget(many, 3)

    first = fit(many, "별칭09z", budget)
    second = fit(many, "별칭09z", budget)

    assert first.selected_tables == second.selected_tables
    assert first.metadata == second.metadata


def test_a_larger_budget_keeps_more_tables(many: ProjectMetadata) -> None:
    few = fit(many, "별칭09z", small_budget(many, 2)).selected_tables
    more = fit(many, "별칭09z", small_budget(many, 6)).selected_tables

    assert len(more) > len(few)
    assert set(few) <= set(more)


# ---- 담을 수 없을 때 ----


def test_a_budget_smaller_than_the_rules_is_a_clear_error(
    many: ProjectMetadata,
) -> None:
    with pytest.raises(PromptTooLargeError) as info:
        fit(many, "질문", 50)

    assert info.value.code == "PROMPT_TOO_LARGE"
    assert "TEXT2SQL_LLM_CONTEXT_TOKENS" in info.value.message


def test_a_budget_that_cannot_hold_one_table_is_a_clear_error(
    many: ProjectMetadata,
) -> None:
    from text2sql.pipeline.budget import _reduce

    base = cost_of(_reduce(many, (), ()))

    with pytest.raises(PromptTooLargeError) as info:
        fit(many, "질문", base + 5)

    assert "하나만으로도" in info.value.message


def test_the_startup_check_reports_a_budget_that_holds_no_table(
    many: ProjectMetadata,
) -> None:
    problems = check_prompt_budget(many, rules_of(many), 50, question_chars=500)

    assert len(problems) == 1
    assert "TEXT2SQL_LLM_CONTEXT_TOKENS" in problems[0]


def test_the_startup_check_passes_when_every_table_fits(many: ProjectMetadata) -> None:
    assert check_prompt_budget(many, rules_of(many), 5000, question_chars=500) == []


# ---- SqlGenerator ----


def test_the_generator_shows_only_the_chosen_tables_to_the_model(
    many: ProjectMetadata,
) -> None:
    llm = FakeLLM("SELECT LABEL FROM T09")
    generator = SqlGenerator(
        llm,
        max_repair_attempts=0,
        max_rows=MAX_ROWS,
        prompt_budget_tokens=small_budget(many, 3),
    )

    result = generator.run("별칭09z 값을 보여줘", many)

    system = llm.prompts[0][0].content
    assert result.status is Status.OK
    assert "T09:" in system
    assert "T00:" not in system
    assert "[규칙]" in system or "규칙:" in system  # 기본 규칙은 잘리지 않는다
    assert system.count("\nT") < COUNT


def test_validation_still_uses_every_real_table(many: ProjectMetadata) -> None:
    # 프롬프트에서 뺀 테이블이라도 실제로 있는 테이블이면 검증은 허용한다
    llm = FakeLLM("SELECT LABEL FROM T00")
    generator = SqlGenerator(
        llm,
        max_repair_attempts=0,
        max_rows=MAX_ROWS,
        prompt_budget_tokens=small_budget(many, 2),
    )

    result = generator.run("별칭09z", many)

    assert result.status is Status.OK
    assert [r.table for r in result.references] == ["T00"]


def test_without_a_budget_the_prompt_is_never_cut(many: ProjectMetadata) -> None:
    llm = FakeLLM("SELECT LABEL FROM T09")

    SqlGenerator(llm, max_repair_attempts=0, max_rows=MAX_ROWS).run("별칭09z", many)

    system = llm.prompts[0][0].content
    assert all(f"T{i:02d}:" in system for i in range(COUNT))


def test_cutting_the_prompt_is_logged_in_korean(
    many: ProjectMetadata, caplog: pytest.LogCaptureFixture
) -> None:
    generator = SqlGenerator(
        FakeLLM("SELECT LABEL FROM T09"),
        max_repair_attempts=0,
        max_rows=MAX_ROWS,
        prompt_budget_tokens=small_budget(many, 3),
    )

    with caplog.at_level(logging.INFO, logger="text2sql.pipeline.run"):
        generator.run("별칭09z", many, request_id="req-1")

    messages = [r.getMessage() for r in caplog.records]
    assert any("프롬프트가 예산을 넘어" in m and "req-1" in m for m in messages)
    assert all("별칭09z" not in m for m in messages)  # 질문 내용은 남기지 않는다


def test_a_prompt_that_fits_logs_nothing_about_cutting(
    many: ProjectMetadata, caplog: pytest.LogCaptureFixture
) -> None:
    generator = SqlGenerator(
        FakeLLM("SELECT LABEL FROM T09"),
        max_repair_attempts=0,
        max_rows=MAX_ROWS,
        prompt_budget_tokens=10**6,
    )

    with caplog.at_level(logging.INFO, logger="text2sql.pipeline.run"):
        generator.run("별칭09z", many)

    assert not any("프롬프트가 예산을 넘어" in r.getMessage() for r in caplog.records)


# ---- 예시가 쓰는 테이블 ----


@pytest.mark.parametrize(
    ("sql", "dialect", "expected"),
    [
        ("SELECT A FROM t1", "oracle", {"T1"}),
        ("SELECT * FROM a JOIN b ON a.x = b.x", "postgres", {"A", "B"}),
        ("WITH c AS (SELECT 1 AS n FROM d) SELECT n FROM c", "oracle", {"D"}),
        ("SELECT (SELECT MAX(x) FROM e) FROM f", "oracle", {"E", "F"}),
        ("SELECT FROM WHERE ((", "oracle", set()),
    ],
)
def test_example_tables_are_read_from_the_sql(
    sql: str, dialect: str, expected: set[str]
) -> None:
    assert extract_table_names(sql, dialect=dialect) == frozenset(expected)


# ---- 시작할 때 ----


def test_startup_fails_when_the_context_cannot_hold_any_table() -> None:
    settings = Settings(_env_file=None, llm_context_tokens=1500)

    with pytest.raises(MetadataError) as info:
        load_registry(settings)

    assert "TEXT2SQL_LLM_CONTEXT_TOKENS" in info.value.message
    assert "p001" in info.value.message


def test_startup_passes_with_the_default_context() -> None:
    assert load_registry(Settings(_env_file=None)).get("p001") is not None


def test_the_context_settings_have_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_context_tokens == 16384
    assert settings.llm_chars_per_token == 1.8
