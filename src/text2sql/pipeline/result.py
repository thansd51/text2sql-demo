from dataclasses import dataclass
from enum import StrEnum

from text2sql.pipeline.references import Reference


class Status(StrEnum):
    OK = "OK"
    REJECTED = "REJECTED"


# 거부 사유 코드 (영어 상수)
REASON_OUT_OF_SCOPE = "QUESTION_OUT_OF_SCOPE"
REASON_VALIDATION_FAILED = "SQL_VALIDATION_FAILED"


@dataclass(frozen=True)
class Reason:
    code: str
    message: str  # 한국어


@dataclass(frozen=True)
class GenerationResult:
    """SQL 생성 결과.

    OK이면 sql은 검증을 통과하고 행 제한이 걸린 최종 SQL이다. REJECTED이면 sql은
    None이다 (거부된 SQL은 응답에 담지 않는다).
    """

    status: Status
    sql: str | None
    attempts: int
    reason: Reason | None = None
    # OK일 때 질문이 쓰는 테이블과 컬럼. REJECTED이면 비어 있다.
    references: tuple[Reference, ...] = ()
