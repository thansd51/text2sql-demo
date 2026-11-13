from sqlglot import exp

from text2sql.dialects.base import BaseDialectAdapter, own_row_limit
from text2sql.dialects.errors import RowLimitError

_EMPTY_STRING_COMPARISONS = (exp.EQ, exp.NEQ, exp.Like, exp.In)
# FETCH FIRST ... ROWS ONLY는 Oracle 12c부터 쓸 수 있다.
_FETCH_FIRST_MIN_MAJOR = 12


class OracleAdapter(BaseDialectAdapter):
    db_type = "oracle"
    sqlglot_dialect = "oracle"
    extra_functions = (exp.CurrentTimestamp,)  # SYSDATE는 CURRENT_TIMESTAMP로 파싱된다

    @property
    def supports_fetch_first(self) -> bool:
        return self.major_version >= _FETCH_FIRST_MIN_MAJOR

    def prompt_rules(self) -> str:
        rules = [
            f"대상 DB는 Oracle {self.db_version}입니다. 이 DB의 문법으로 SELECT 한 문장만 작성합니다 (CTE와 UNION은 사용할 수 있습니다).",
            "문자열 연결은 || 를 사용합니다.",
            "테이블 별칭에는 AS를 쓰지 않습니다. 예: FROM OBJ_MAIN T1. 컬럼 별칭에는 AS를 쓸 수 있습니다.",
            "Oracle에서 빈 문자열('')은 NULL입니다. = '' 비교 대신 IS NULL / IS NOT NULL을 사용합니다.",
            "CAST로 문자형으로 바꿀 때는 VARCHAR2(100)처럼 길이를 지정합니다.",
            "모든 SELECT에는 FROM 절이 있어야 합니다. FROM DUAL은 사용할 수 없습니다.",
            "오늘 날짜가 필요하면 TO_CHAR(SYSDATE, 'YYYYMMDD')로 날짜 문자열을 만듭니다. ADD_MONTHS, TRUNC 같은 날짜 계산 함수는 사용할 수 없습니다.",
            "스키마 이름, 힌트, 재귀 CTE, OFFSET은 사용하지 않습니다.",
        ]
        if self.supports_fetch_first:
            rules.append(
                "개수를 제한해야 하면 최상위 질의 끝에 FETCH FIRST N ROWS ONLY를 사용합니다. 하위 질의 안에서는 쓰지 않습니다."
            )
        else:
            rules.append(
                f"Oracle {self.db_version}에서는 FETCH FIRST를 쓸 수 없습니다. 개수를 제한해야 하면 정렬한 질의를 하위 질의로 감싸고 바깥 WHERE에서 ROWNUM <= N을 사용합니다."
            )
        return "\n".join(f"- {rule}" for rule in rules)

    def check(self, expression: exp.Expression) -> list[str]:
        violations: list[str] = []
        for literal in expression.find_all(exp.Literal):
            if literal.is_string and literal.name == "" and _is_compared(literal):
                violations.append(
                    "Oracle에서 빈 문자열('')은 NULL이라 비교할 수 없습니다. IS NULL / IS NOT NULL을 사용하세요"
                )
        for cast in expression.find_all(exp.Cast):
            if cast.to.is_type("varchar", "nvarchar") and not cast.to.expressions:
                violations.append(
                    "Oracle에서 문자형으로 CAST할 때는 길이를 지정해야 합니다 (예: VARCHAR2(100))"
                )
        if expression.find(exp.Offset):
            violations.append("Oracle에서는 OFFSET을 지원하지 않습니다")
        if not self.supports_fetch_first and expression.find(exp.Fetch):
            violations.append(
                f"Oracle {self.db_version}에서는 FETCH FIRST를 쓸 수 없습니다"
            )
        return violations

    def _limit(self, query: exp.Query, max_rows: int) -> exp.Query:
        # 버전과 무관하게 ROWNUM으로 감싼다 (docs/design.md "검증과 방언의 경계").
        # 질의 자체의 행 제한은 안쪽에서 빼고, 바깥 ROWNUM에 둘 중 작은 값을 쓴다.
        # 안쪽에 남기면 최종 검증의 "행 제한은 최상위 질의에만" 규칙에 걸린다.
        own = own_row_limit(query)
        if query.args.get("offset"):
            raise RowLimitError(
                "Oracle에서는 OFFSET이 있는 질의에 행 제한을 적용할 수 없습니다"
            )
        effective = max_rows if own is None else min(own, max_rows)
        inner = query.copy()
        inner.set("limit", None)
        with_clause = inner.args.get("with_")
        inner.set("with_", None)
        rownum = exp.LTE(
            this=exp.column("ROWNUM"), expression=exp.Literal.number(effective)
        )
        outer = exp.select("*").from_(inner.subquery(copy=False)).where(rownum)
        if with_clause is not None:
            # WITH는 바깥으로 올린다. 안쪽 질의가 CTE를 그대로 참조한다.
            outer.set("with_", with_clause)
        return outer


def _is_compared(literal: exp.Literal) -> bool:
    parent = literal.parent
    while isinstance(parent, exp.Paren):
        parent = parent.parent
    return isinstance(parent, _EMPTY_STRING_COMPARISONS)
