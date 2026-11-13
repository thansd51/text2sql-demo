from sqlglot import exp

from text2sql.dialects.base import BaseDialectAdapter, own_row_limit


class PostgresqlAdapter(BaseDialectAdapter):
    db_type = "postgresql"
    sqlglot_dialect = "postgres"  # sqlglot은 "postgresql"을 인식하지 못한다
    extra_functions = (exp.CurrentDate,)

    def prompt_rules(self) -> str:
        rules = [
            f"대상 DB는 PostgreSQL {self.db_version}입니다. 이 DB의 문법으로 SELECT 한 문장만 작성합니다 (CTE와 UNION은 사용할 수 있습니다).",
            "문자열 연결은 || 또는 CONCAT을 사용합니다.",
            "개수를 제한해야 하면 최상위 질의 끝에 LIMIT N을 사용합니다. 하위 질의 안에서는 LIMIT을 쓰지 않습니다.",
            "모든 SELECT에는 FROM 절이 있어야 합니다.",
            "오늘 날짜가 필요하면 TO_CHAR(CURRENT_DATE, 'YYYYMMDD')로 날짜 문자열을 만듭니다. INTERVAL, DATE_TRUNC 같은 날짜 계산 함수는 사용할 수 없습니다.",
            "스키마 이름을 붙이거나 재귀 CTE를 쓰지 않습니다.",
        ]
        return "\n".join(f"- {rule}" for rule in rules)

    def _limit(self, query: exp.Query, max_rows: int) -> exp.Query:
        own = own_row_limit(query)
        effective = max_rows if own is None else min(own, max_rows)
        # limit()은 기존 OFFSET을 보존하고 FETCH FIRST를 LIMIT으로 바꾼다.
        return query.limit(effective)
