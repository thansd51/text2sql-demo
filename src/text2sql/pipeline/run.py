"""질문에서 최종 SQL까지 (docs/design.md "요청 처리" 2~6).

프롬프트 → LLM → 1차 검증(허용 테이블과 컬럼) → 실패하면 오류를 넣어 재시도 →
행 제한 강제 → 최종 검증(허용 테이블).

LLM 오류(LLMUnavailableError, LLMTimeoutError), 방언 오류(DialectError), 서버가 만든
SQL의 문제(PipelineError)는 잡지 않고 그대로 올린다. 응답으로 바꾸는 일은 api가 한다.
"""

import logging
import re

from text2sql.dialects import DialectAdapter, RowLimitError, get_adapter
from text2sql.llm import LLMClient
from text2sql.pipeline.budget import DEFAULT_CHARS_PER_TOKEN, fit_metadata
from text2sql.pipeline.errors import FinalValidationError
from text2sql.pipeline.prompt import UNSUPPORTED_ANSWER, build_messages
from text2sql.pipeline.references import extract_references
from text2sql.pipeline.result import (
    REASON_OUT_OF_SCOPE,
    REASON_VALIDATION_FAILED,
    GenerationResult,
    Reason,
    Status,
)
from text2sql.semantic import ProjectMetadata
from text2sql.validation import Stage, Violation, validate_sql

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```[a-zA-Z]*\s*(.*?)```", re.DOTALL)


class SqlGenerator:
    def __init__(
        self,
        llm: LLMClient,
        max_repair_attempts: int,
        *,
        max_rows: int,
        prompt_budget_tokens: int | None = None,
        chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
    ) -> None:
        if max_repair_attempts < 0:
            raise ValueError("재시도 횟수는 0 이상이어야 합니다")
        if max_rows < 1:
            raise ValueError("최대 행 수는 1 이상이어야 합니다")
        self._llm = llm
        self._max_repair_attempts = max_repair_attempts
        self._max_rows = max_rows
        # None이면 프롬프트를 줄이지 않는다
        self._prompt_budget_tokens = prompt_budget_tokens
        self._chars_per_token = chars_per_token

    def run(
        self,
        question: str,
        metadata: ProjectMetadata,
        *,
        request_id: str | None = None,
    ) -> GenerationResult:
        datasource = metadata.datasource
        adapter = get_adapter(datasource.db_type, datasource.db_version)
        dialect_rules = adapter.prompt_rules()
        total = self._max_repair_attempts + 1
        # 프롬프트에 넣을 메타데이터. 예산을 넘으면 질문과 관련 있는 테이블로 줄인다.
        # 검증은 줄이지 않은 전체 메타데이터 기준이다 (실제 존재하는 테이블이면 허용).
        shown = self._fit(metadata, dialect_rules, question, adapter, request_id)

        previous_sql: str | None = None
        errors: tuple[str, ...] = ()
        for attempt in range(1, total + 1):
            messages = build_messages(
                shown, dialect_rules, question, previous_sql, errors
            )
            sql = extract_sql(self._llm.complete(messages))
            if sql.rstrip(".;").strip().upper() == UNSUPPORTED_ANSWER:
                return GenerationResult(
                    status=Status.REJECTED,
                    sql=None,
                    attempts=attempt,
                    reason=Reason(
                        REASON_OUT_OF_SCOPE, "이 질문은 현재 스키마로 답할 수 없습니다"
                    ),
                )
            result = validate_sql(
                sql,
                stage=Stage.FIRST,
                dialect=adapter.sqlglot_dialect,
                allowed_tables=metadata.table_names(),
                allowed_columns=metadata.columns_by_table(),
                extra_functions=adapter.extra_functions,
                dialect_check=adapter.check,
            )
            if result.ok and result.sql is not None:
                try:
                    final_sql = finish_sql(
                        result.sql, metadata, adapter, self._max_rows
                    )
                except RowLimitError as e:
                    # LLM이 쓴 행 제한을 서버가 다룰 수 없는 형태다. 오류를 알려 다시 쓰게 한다.
                    problems: tuple[str, ...] = (f"{e.code}: {e.message}",)
                else:
                    references = extract_references(
                        result.sql,
                        dialect=adapter.sqlglot_dialect,
                        columns_by_table=metadata.columns_by_table(),
                    )
                    return GenerationResult(
                        Status.OK, final_sql, attempt, references=references
                    )
            else:
                problems = tuple(_describe(v) for v in result.violations)

            previous_sql = sql
            errors = problems
            # 거부된 SQL 전체는 로그에 남기지 않는다. 검증 사유(코드와 메시지)만 남긴다.
            logger.warning(
                "SQL 검증 실패 (요청 %s, 시도 %d/%d): %s",
                request_id or "-",
                attempt,
                total,
                "; ".join(errors),
            )

        return GenerationResult(
            status=Status.REJECTED,
            sql=None,
            attempts=total,
            reason=Reason(REASON_VALIDATION_FAILED, "유효한 SQL을 생성하지 못했습니다"),
        )

    def _fit(
        self,
        metadata: ProjectMetadata,
        dialect_rules: str,
        question: str,
        adapter: DialectAdapter,
        request_id: str | None,
    ) -> ProjectMetadata:
        if self._prompt_budget_tokens is None:
            return metadata
        fit = fit_metadata(
            metadata,
            dialect_rules,
            question,
            self._prompt_budget_tokens,
            chars_per_token=self._chars_per_token,
            dialect=adapter.sqlglot_dialect,
        )
        if fit.reduced:
            logger.info(
                "프롬프트가 예산을 넘어 테이블 %d개 중 %d개만 넣었습니다 "
                "(요청 %s, 예상 %d/%d토큰): %s",
                len(metadata.tables),
                len(fit.selected_tables),
                request_id or "-",
                fit.estimated_tokens,
                self._prompt_budget_tokens,
                ", ".join(fit.selected_tables),
            )
        return fit.metadata


def finish_sql(
    sql: str, metadata: ProjectMetadata, adapter: DialectAdapter, max_rows: int
) -> str:
    """1차 검증을 통과한 SQL에 행 제한을 걸고 최종 검증한다 (설계서 5~6단계).

    RowLimitError는 LLM이 쓴 SQL 때문일 수 있어 호출한 쪽이 재시도로 다룬다.
    최종 검증 실패는 서버 쪽 문제라서 PipelineError로 올린다.
    """
    limited = adapter.apply_row_limit(sql, max_rows)
    final = validate_sql(
        limited,
        stage=Stage.FINAL,
        dialect=adapter.sqlglot_dialect,
        allowed_tables=metadata.table_names(),
        extra_functions=adapter.extra_functions,
    )
    if not final.ok or final.sql is None:
        codes = ", ".join(sorted({v.code.value for v in final.violations}))
        raise FinalValidationError(
            f"행 제한을 건 SQL이 최종 검증을 통과하지 못했습니다 ({codes})"
        )
    return final.sql


def check_example(
    sql: str, metadata: ProjectMetadata, adapter: DialectAdapter
) -> list[str]:
    """예시 SQL이 이 프로젝트의 테이블과 DB에서 통과하는지 확인한다.

    모델이 쓴 SQL과 똑같이 1차 검증, 행 제한, 최종 검증을 거친다. 통과하지 못하면
    사유(한국어) 목록을, 통과하면 빈 목록을 돌려준다. 공통 예시 하나가 틀리면 모든
    프로젝트의 프롬프트를 오염시키므로 시작할 때 확인하는 데 쓴다.
    """
    first = validate_sql(
        sql,
        stage=Stage.FIRST,
        dialect=adapter.sqlglot_dialect,
        allowed_tables=metadata.table_names(),
        allowed_columns=metadata.columns_by_table(),
        extra_functions=adapter.extra_functions,
        dialect_check=adapter.check,
    )
    if not first.ok or first.sql is None:
        return [_describe(v) for v in first.violations]
    try:
        finish_sql(first.sql, metadata, adapter, 1)
    except (RowLimitError, FinalValidationError) as e:
        return [e.message]
    return []


def extract_sql(text: str) -> str:
    """LLM 답변에서 SQL만 꺼낸다. 코드블록이 있으면 그 안의 내용을 쓴다."""
    fenced = _FENCE.search(text)
    return (fenced.group(1) if fenced else text).strip()


def _describe(violation: Violation) -> str:
    return f"{violation.code.value}: {violation.message}"
