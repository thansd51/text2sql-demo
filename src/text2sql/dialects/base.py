"""방언 어댑터 인터페이스와 공통 구현.

LLM이 대상 DB 문법으로 SQL을 직접 쓰므로 SQL 변환(transpile)은 하지 않는다.
어댑터는 (1) 프롬프트용 방언 규칙 문구, (2) 검증용 sqlglot 방언 이름,
(3) 행 제한 강제, (4) 1차 검증용 방언 점검을 제공한다.

이 패키지는 validation을 import하지 않는다. pipeline이 둘을 연결한다.
"""

import re
from abc import ABC, abstractmethod
from typing import ClassVar, Protocol

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from text2sql.dialects.errors import InvalidDbVersionError, RowLimitError

_MAJOR_VERSION = re.compile(r"\s*(\d+)")


class DialectAdapter(Protocol):
    """DB 종류마다 달라지는 것. 구현 교체가 필요한 지점이라 인터페이스를 둔다."""

    db_type: str
    db_version: str
    sqlglot_dialect: str
    # 모델이 쓸 수 있는 현재 날짜 함수 (Oracle SYSDATE, PostgreSQL CURRENT_DATE). 검증이 허용한다.
    extra_functions: tuple[type[exp.Expression], ...]

    def prompt_rules(self) -> str:
        """프롬프트에 넣을 방언 규칙 문구(한국어)."""
        ...

    def apply_row_limit(self, sql: str, max_rows: int) -> str:
        """최대 행 수를 강제한 SQL을 돌려준다."""
        ...

    def check(self, expression: exp.Expression) -> list[str]:
        """1차 검증용 방언 점검. 위반 사유(한국어) 목록, 없으면 빈 목록."""
        ...


def own_row_limit(query: exp.Query) -> int | None:
    """질의에 이미 있는 행 제한(LIMIT, FETCH FIRST)을 읽는다.

    정수 리터럴이 아니거나 PERCENT, WITH TIES이면 안전하게 거부한다.
    """
    node = query.args.get("limit")
    if node is None:
        return None
    options = node.args.get("limit_options")
    if options is not None and (
        options.args.get("percent") or options.args.get("with_ties")
    ):
        raise RowLimitError("PERCENT, WITH TIES 행 제한은 지원하지 않습니다")
    count = node.args.get("count") if isinstance(node, exp.Fetch) else node.expression
    if not (isinstance(count, exp.Literal) and count.is_int):
        raise RowLimitError("행 제한 값은 정수 리터럴이어야 합니다")
    return int(count.name)


def parse_major_version(db_version: str) -> int:
    """ "19c", "12.2", "11g", "14" 같은 문자열에서 주 버전 숫자를 읽는다."""
    match = _MAJOR_VERSION.match(db_version or "")
    if match is None:
        raise InvalidDbVersionError(
            f"DB 버전을 해석할 수 없습니다: {db_version!r} (예: 19c, 12.2, 14)"
        )
    return int(match.group(1))


class BaseDialectAdapter(ABC):
    db_type: ClassVar[str]
    sqlglot_dialect: ClassVar[str]
    extra_functions: ClassVar[tuple[type[exp.Expression], ...]]

    def __init__(self, db_version: str) -> None:
        self.db_version = db_version
        self.major_version = parse_major_version(db_version)

    @abstractmethod
    def prompt_rules(self) -> str: ...

    @abstractmethod
    def _limit(self, query: exp.Query, max_rows: int) -> exp.Query:
        """질의에 최대 행 수를 강제한다."""

    def check(self, expression: exp.Expression) -> list[str]:
        return []

    def apply_row_limit(self, sql: str, max_rows: int) -> str:
        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
            raise RowLimitError("최대 행 수는 1 이상의 정수여야 합니다")
        limited = self._limit(self._parse_query(sql), max_rows)
        return limited.sql(dialect=self.sqlglot_dialect, comments=False)

    def _parse_query(self, sql: str) -> exp.Query:
        try:
            statements = [s for s in sqlglot.parse(sql, read=self.sqlglot_dialect) if s]
        except SqlglotError as e:
            raise RowLimitError(
                f"행 제한을 적용할 SQL을 분석하지 못했습니다 ({type(e).__name__})"
            ) from e
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            raise RowLimitError("행 제한은 SELECT 한 문장에만 적용할 수 있습니다")
        return statements[0]
