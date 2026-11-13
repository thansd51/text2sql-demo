"""프롬프트 크기 관리 (docs/design.md "프롬프트 크기와 테이블 선택").

테이블이 수십 개로 늘면 스키마 전체가 모델의 컨텍스트에 들어가지 않는다. 컨텍스트가
작은 로컬 모델(Ollama 등)은 넘치면 앞부분(규칙)부터 조용히 잘릴 수 있어서, 서버가
토큰 예산을 계산해 넘기지 않게 줄인다.

- 전체가 예산에 들어가면 아무것도 줄이지 않는다 (컨텍스트가 큰 클라우드 모델).
- 넘으면 질문과 관련 있는 테이블만 골라 넣는다. 관련 있는 테이블과 조인되는 테이블을
  함께 넣고, 줄인 스키마에 맞춰 관계, 코드 값, 예시도 걸러 낸다.
- 예산이 테이블 하나도 담지 못하면 PromptTooLargeError. 시작할 때도 같은 검사를 한다.

테이블 고르기는 LLM을 쓰지 않는다. 질문에 테이블 이름, 컬럼 이름, 동의어, 코드 이름,
설명의 단어가 나오는지로 점수를 매긴다. 같은 입력이면 항상 같은 결과다.
"""

import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from text2sql.pipeline.errors import PromptTooLargeError
from text2sql.pipeline.prompt import build_system_prompt
from text2sql.pipeline.references import extract_table_names
from text2sql.semantic import Example, ProjectMetadata, Table

logger = logging.getLogger(__name__)

# 한국어가 섞인 이 프로젝트의 프롬프트로 직접 잰 값은 1글자당 약 0.54토큰(4,943자 2,655토큰,
# 로컬 모델 토크나이저)이다. 토크나이저는 모델마다 달라서 넉넉하게 어림하고, 모델이
# 다르면 설정(TEXT2SQL_LLM_CHARS_PER_TOKEN)으로 바꾼다.
DEFAULT_CHARS_PER_TOKEN = 1.8
# 재시도할 때 붙는 이전 답변과 오류 목록을 위해 남겨 두는 토큰
RETRY_RESERVE_TOKENS = 800
# 테이블(스키마)이 쓸 수 있는 비율. 나머지는 예시에 남긴다. 예시가 하나도 못 들어갈 만큼
# 테이블이 차지하지 않게 하려는 값이다 (모델 품질에 미치는 영향은 확인 못 함).
TABLE_SHARE = 0.7
_USER_PREFIX = "질문: "
_WORD = re.compile(r"[가-힣A-Za-z0-9_]{2,}")

# 점수 가중치. 이름과 동의어가 질문에 직접 나오면 크게, 설명의 단어는 작게 센다.
_W_TABLE_NAME = 5
_W_CODE_NAME = 4
_W_SYNONYM = 3
_W_COLUMN_NAME = 3
_W_GROUP = 1
_W_WORD = 1
_MAX_WORD_SCORE = 5


def estimate_tokens(text: str, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> int:
    """글자 수로 토큰 수를 넉넉하게 어림한다 (올림)."""
    return math.ceil(len(text) / chars_per_token)


def prompt_budget_tokens(context_tokens: int, answer_tokens: int) -> int:
    """컨텍스트에서 답변과 재시도 여유를 뺀, 프롬프트(시스템 + 질문)가 쓸 수 있는 토큰."""
    return context_tokens - answer_tokens - RETRY_RESERVE_TOKENS


@dataclass(frozen=True)
class Fit:
    """줄인 결과. metadata가 같은 객체면 줄이지 않은 것이다."""

    metadata: ProjectMetadata
    reduced: bool
    estimated_tokens: int
    selected_tables: tuple[str, ...]


def fit_metadata(
    metadata: ProjectMetadata,
    dialect_rules: str,
    question: str,
    budget_tokens: int,
    *,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
    dialect: str = "",
) -> Fit:
    """프롬프트가 예산에 들어가도록 메타데이터를 줄인다. 들어가면 그대로 돌려준다."""

    def cost(candidate: ProjectMetadata) -> int:
        text = build_system_prompt(candidate, dialect_rules) + _USER_PREFIX + question
        return estimate_tokens(text, chars_per_token)

    full = cost(metadata)
    all_tables = tuple(table.name for table in metadata.tables)
    if full <= budget_tokens:
        return Fit(metadata, False, full, all_tables)

    base = _reduce(metadata, (), examples=())
    base_cost = cost(base)
    if base_cost >= budget_tokens:
        raise PromptTooLargeError(
            f"규칙과 용어집만으로 프롬프트({base_cost}토큰)가 예산({budget_tokens}토큰)을 "
            "넘습니다. 모델의 컨텍스트 설정(TEXT2SQL_LLM_CONTEXT_TOKENS)을 확인하세요"
        )
    free = budget_tokens - base_cost
    table_allowance = int(free * TABLE_SHARE)

    selected: list[str] = []

    def try_add(name: str) -> bool:
        if name in selected:
            return False
        trial = _reduce(metadata, (*selected, name), examples=())
        used = cost(trial) - base_cost
        # 첫 테이블은 예시 몫까지 쓸 수 있다 (테이블 하나도 못 넣는 것보다 낫다)
        limit = table_allowance if selected else free
        if used > limit:
            return False
        selected.append(name)
        return True

    scores = score_tables(metadata, question)
    ranked = sorted(
        range(len(metadata.tables)),
        key=lambda i: (-scores[metadata.tables[i].name], i),
    )
    for index in ranked:
        name = metadata.tables[index].name
        # 점수가 있는 테이블을 먼저 담는다. 점수가 하나도 없으면 파일 순서로 채운다.
        if scores[name] > 0 or not any(scores.values()):
            try_add(name)
    for name in _neighbors(metadata, tuple(selected)):
        try_add(name)

    if not selected:
        first = min(
            metadata.tables, key=lambda t: cost(_reduce(metadata, (t.name,), ()))
        )
        alone = cost(_reduce(metadata, (first.name,), examples=()))
        raise PromptTooLargeError(
            f"테이블 {first.name} 하나만으로도 프롬프트({alone}토큰)가 예산"
            f"({budget_tokens}토큰)을 넘습니다. 모델의 컨텍스트 설정"
            "(TEXT2SQL_LLM_CONTEXT_TOKENS)을 확인하세요"
        )

    chosen = _reduce(metadata, tuple(selected), examples=())
    examples = []
    selected_upper = {name.upper() for name in selected}
    for example in metadata.examples:
        used_tables = extract_table_names(example.sql, dialect=dialect)
        if not used_tables or not used_tables <= selected_upper:
            continue
        trial = chosen.model_copy(update={"examples": (*examples, example)})
        if cost(trial) <= budget_tokens:
            examples.append(example)
    final = chosen.model_copy(update={"examples": tuple(examples)})
    return Fit(
        final,
        True,
        cost(final),
        tuple(t.name for t in final.tables),
    )


def check_prompt_budget(
    metadata: ProjectMetadata,
    dialect_rules: str,
    budget_tokens: int,
    *,
    question_chars: int,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> list[str]:
    """어떤 질문에서도 테이블 하나는 담을 수 있는지 확인한다 (시작할 때 쓴다).

    문제가 있으면 한국어 사유 목록을, 없으면 빈 목록을 돌려준다.
    """
    question = "가" * question_chars
    try:
        for table in metadata.tables:
            only = _reduce(metadata, (table.name,), examples=())
            # 테이블 하나만 두고 줄여 본다. 하나도 못 담으면 PromptTooLargeError가 난다.
            fit_metadata(
                only,
                dialect_rules,
                question,
                budget_tokens,
                chars_per_token=chars_per_token,
            )
    except PromptTooLargeError as e:
        return [e.message]
    return []


def score_tables(metadata: ProjectMetadata, question: str) -> dict[str, int]:
    """테이블 이름 -> 질문과의 관련도 점수. 0이면 질문에서 아무 단서도 못 찾았다는 뜻이다."""
    text = question.lower()
    code_hits = _code_name_hits(metadata, text)
    return {
        table.name: _score(table, text) + code_hits.get(table.name.upper(), 0)
        for table in metadata.tables
    }


def _score(table: Table, text: str) -> int:
    score = 0
    if table.name.lower() in text:
        score += _W_TABLE_NAME
    if table.group and table.group.lower() in text:
        score += _W_GROUP
    for column in table.columns:
        # 짧은 컬럼 이름(SID, SEQ)은 우연히 들어맞기 쉬워서 3글자 이상만 본다
        if len(column.name) >= 3 and column.name.lower() in text:
            score += _W_COLUMN_NAME
        score += sum(
            _W_SYNONYM for word in set(column.synonyms) if word.lower() in text
        )
    words = set(_WORD.findall(table.description.lower()))
    for column in table.columns:
        words |= set(_WORD.findall(column.description.lower()))
    matched = sum(1 for word in words if word in text)
    return score + min(matched, _MAX_WORD_SCORE) * _W_WORD


def _code_name_hits(metadata: ProjectMetadata, text: str) -> dict[str, int]:
    """질문에 테이블 데이터의 값(장기상품 등)이 나오면 그 행이 속한 테이블에 점수를 준다.

    숫자만으로 된 값(101)은 질문의 다른 숫자와 우연히 겹치기 쉬워서 뺀다.
    """
    hits: dict[str, int] = {}
    for table, rows in metadata.table_data.items():
        values = {
            value.lower()
            for row in rows
            for value in row.values()
            if value and len(value) >= 2 and not value.isdigit()
        }
        count = sum(1 for value in values if value in text)
        if count:
            hits[table.upper()] = count * _W_CODE_NAME
    return hits


def _neighbors(metadata: ProjectMetadata, selected: tuple[str, ...]) -> list[str]:
    """고른 테이블과 조인 키로 이어진 테이블 (고른 순서, 이어진 순서)."""
    real = {table.name.upper(): table.name for table in metadata.tables}
    chosen = {name.upper() for name in selected}
    found: list[str] = []
    for name in selected:
        for item in metadata.relationships:
            ends = (
                item.source.split(".")[0].upper(),
                item.target.split(".")[0].upper(),
            )
            if name.upper() not in ends:
                continue
            for end in ends:
                if end in real and end not in chosen and real[end] not in found:
                    found.append(real[end])
    return found


def _reduce(
    metadata: ProjectMetadata, names: Iterable[str], examples: Iterable[Example]
) -> ProjectMetadata:
    """고른 테이블만 남긴 메타데이터. 테이블 순서는 원래 순서를 지킨다."""
    keep = {name.upper() for name in names}
    return metadata.model_copy(
        update={
            "tables": tuple(t for t in metadata.tables if t.name.upper() in keep),
            "table_data": {
                table: rows
                for table, rows in metadata.table_data.items()
                if table.upper() in keep
            },
            "relationships": tuple(
                item
                for item in metadata.relationships
                if item.source.split(".")[0].upper() in keep
                and item.target.split(".")[0].upper() in keep
            ),
            "examples": tuple(examples),
        }
    )
