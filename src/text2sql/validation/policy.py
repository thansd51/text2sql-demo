"""SQL 검증 정책.

허용 목록 방식이다. 명시적으로 허용하지 않은 것은 모두 거부한다. 루트 노드만이
아니라 AST 전체를 검사한다. 통과한 SQL은 원문이 아니라 AST에서 주석 없이 다시
생성한 문자열을 돌려준다.

허용 SQL은 SELECT(CTE, UNION 포함)뿐이다. CREATE VIEW를 포함한 모든 CREATE는
어느 단계에서도 거부한다.

이 모듈은 특정 제품(테이블, 뷰, 컬럼)을 알지 못한다. 허용 목록은 모두 인자로 받고,
방언 의존 규칙은 호출자(pipeline)가 함수로 넘긴다. dialects를 import하지 않는다.
"""

from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify


class Stage(StrEnum):
    # 1차 검증: LLM이 쓴 SQL. 방언 전용 점검(dialect_check)과 컬럼 확인을 한다.
    FIRST = "first"
    # 최종 검증: 행 제한까지 건 SQL. 구조, 허용 테이블, 금지 노드만 본다.
    FINAL = "final"


class ViolationCode(StrEnum):
    PARSE_ERROR = "PARSE_ERROR"
    MULTIPLE_STATEMENTS = "MULTIPLE_STATEMENTS"
    CREATE_NOT_ALLOWED = "CREATE_NOT_ALLOWED"
    STATEMENT_NOT_ALLOWED = "STATEMENT_NOT_ALLOWED"
    FORBIDDEN_NODE = "FORBIDDEN_NODE"
    FORBIDDEN_CLAUSE = "FORBIDDEN_CLAUSE"
    HINT_NOT_ALLOWED = "HINT_NOT_ALLOWED"
    FUNCTION_NOT_ALLOWED = "FUNCTION_NOT_ALLOWED"
    TABLE_NOT_ALLOWED = "TABLE_NOT_ALLOWED"
    COLUMN_NOT_ALLOWED = "COLUMN_NOT_ALLOWED"
    QUERY_SHAPE_NOT_ALLOWED = "QUERY_SHAPE_NOT_ALLOWED"
    DIALECT_RULE = "DIALECT_RULE"


@dataclass(frozen=True)
class Violation:
    code: ViolationCode
    message: str  # 한국어. LLM 재시도 프롬프트와 로그에 쓴다.


@dataclass(frozen=True)
class PolicyResult:
    violations: tuple[Violation, ...]
    sql: str | None = None

    @property
    def ok(self) -> bool:
        return not self.violations


# 방언 전용 점검. 질의를 받아 한국어 위반 사유 목록을 돌려준다. 1차 검증에만 적용한다.
DialectCheck = Callable[[exp.Expression], list[str]]

# 트리 어디에도 나오면 안 되는 노드. CREATE는 별도 코드로 처리한다.
_FORBIDDEN_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Drop",
    "Alter",
    "TruncateTable",
    "Grant",
    "Copy",
    "Command",
    "Set",
    "Transaction",
    "Commit",
    "Rollback",
)
_FORBIDDEN_NODES = tuple(
    getattr(exp, n) for n in _FORBIDDEN_NODE_NAMES if hasattr(exp, n)
)

# 허용 함수 노드 타입. And, Or, Not, Exists 같은 연산자 성격 노드도 exp.Func의
# 하위 클래스라서 함께 나열해야 한다.
_COMMON_FUNCS: tuple[type[exp.Expression], ...] = (
    exp.Count,
    exp.Sum,
    exp.Avg,
    exp.Min,
    exp.Max,
    exp.Upper,
    exp.Lower,
    exp.Trim,
    exp.Substring,
    exp.Length,
    exp.Concat,
    exp.Coalesce,
    exp.Case,
    exp.If,
    exp.Cast,
    exp.TimeToStr,  # TO_CHAR
    exp.RowNumber,
    exp.And,
    exp.Or,
    exp.Not,
    exp.Exists,
)


def validate_sql(
    sql: str,
    *,
    stage: Stage,
    dialect: str,
    allowed_tables: Collection[str],
    allowed_columns: Mapping[str, Collection[str]] | None = None,
    extra_functions: tuple[type[exp.Expression], ...] = (),
    dialect_check: DialectCheck | None = None,
) -> PolicyResult:
    """``sql``을 검증하고, 통과하면 AST에서 다시 생성한 SQL을 돌려준다.

    ``dialect``는 sqlglot 방언 이름이다(예: "oracle", "postgres"). db_type과 다를 수
    있으므로 변환은 호출자가 한다.
    ``allowed_tables``는 허용하는 테이블 이름이다. 정의한 CTE 이름은 자동으로 허용한다.
    ``allowed_columns``는 {테이블 이름: 컬럼 이름 목록}이다. 주어지면 모든 컬럼이 여기에
    있어야 한다.
    ``extra_functions``는 공통 허용 목록에 더하는 함수다. 현재 날짜 함수(Oracle SYSDATE,
    PostgreSQL CURRENT_DATE)처럼 DB마다 다른 것을 어댑터가 알려 준다.
    ``dialect_check``는 방언 전용 점검이며 1차 검증에서만 실행한다. 최종 검증은 구조,
    허용 테이블, 금지 노드만 본다.
    """
    # 구문 분석 실패, 또는 문장이 정확히 하나가 아닌 경우
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except SqlglotError as e:
        return _fail(
            ViolationCode.PARSE_ERROR,
            f"SQL 구문을 분석하지 못했습니다 ({type(e).__name__})",
        )
    if len(statements) != 1:
        return _fail(
            ViolationCode.MULTIPLE_STATEMENTS,
            f"SQL은 정확히 한 문장이어야 합니다 (현재 {len(statements)}문장)",
        )
    root = statements[0]

    violations: list[Violation] = []
    violations += _check_root(root)
    violations += _check_forbidden_nodes(root)
    violations += _check_functions(root, extra_functions)
    if isinstance(root, exp.Query):
        violations += _check_tables(root, allowed_tables)
        violations += _check_columns(root)
        violations += _check_query_shape(root)
        if stage is Stage.FIRST and dialect_check is not None:
            violations += [
                Violation(ViolationCode.DIALECT_RULE, message)
                for message in dialect_check(root)
            ]

    # qualify()는 모르는 테이블을 조용히 통과시키므로 테이블 검사가 깨끗할 때만 실행한다.
    if not violations and allowed_columns is not None:
        violations += _check_column_existence(root, dialect, allowed_columns)

    if violations:
        return PolicyResult(violations=tuple(violations))
    return PolicyResult(violations=(), sql=root.sql(dialect=dialect, comments=False))


def _fail(code: ViolationCode, message: str) -> PolicyResult:
    return PolicyResult(violations=(Violation(code, message),))


def _check_root(root: exp.Expression) -> list[Violation]:
    if isinstance(root, exp.Create) or _is_create_command(root):
        return [
            Violation(
                ViolationCode.CREATE_NOT_ALLOWED,
                "CREATE 문은 허용되지 않습니다 (CREATE VIEW 포함). SELECT만 작성하세요",
            )
        ]
    if not isinstance(root, exp.Query):
        return [
            Violation(
                ViolationCode.STATEMENT_NOT_ALLOWED,
                f"허용되지 않는 문장 종류입니다: {type(root).__name__}",
            )
        ]
    return []


def _is_create_command(node: exp.Expression) -> bool:
    # sqlglot이 일부 CREATE 변형을 Command로 파싱하는 경우를 놓치지 않기 위한 방어
    return isinstance(node, exp.Command) and str(node.this).upper() == "CREATE"


def _check_forbidden_nodes(root: exp.Expression) -> list[Violation]:
    out: list[Violation] = []
    for node in root.walk():
        if isinstance(node, exp.Create) or _is_create_command(node):
            # 루트의 CREATE는 _check_root가 이미 보고했다. 중첩된 CREATE만 추가한다.
            if node is not root:
                out.append(
                    Violation(
                        ViolationCode.CREATE_NOT_ALLOWED,
                        "CREATE 문은 허용되지 않습니다",
                    )
                )
        elif isinstance(node, _FORBIDDEN_NODES):
            out.append(
                Violation(
                    ViolationCode.FORBIDDEN_NODE,
                    f"허용되지 않는 구문입니다: {type(node).__name__}",
                )
            )
        elif isinstance(node, (exp.Into, exp.Lock)):
            out.append(
                Violation(
                    ViolationCode.FORBIDDEN_CLAUSE,
                    f"허용되지 않는 절입니다: {type(node).__name__}",
                )
            )
        elif isinstance(node, exp.Hint):
            out.append(
                Violation(ViolationCode.HINT_NOT_ALLOWED, "힌트는 허용되지 않습니다")
            )
    return out


def _check_functions(
    root: exp.Expression,
    extra_functions: tuple[type[exp.Expression], ...],
) -> list[Violation]:
    allowed = _COMMON_FUNCS + extra_functions
    out: list[Violation] = []
    for node in root.walk():
        if isinstance(node, exp.Dot):
            out.append(
                Violation(
                    ViolationCode.FUNCTION_NOT_ALLOWED,
                    "패키지/스키마를 붙인 호출이나 점(.) 접근은 허용되지 않습니다",
                )
            )
        elif isinstance(node, exp.Anonymous):
            out.append(
                Violation(
                    ViolationCode.FUNCTION_NOT_ALLOWED,
                    f"허용되지 않는 함수입니다: {node.name}",
                )
            )
        elif isinstance(node, exp.Func) and not isinstance(node, allowed):
            out.append(
                Violation(
                    ViolationCode.FUNCTION_NOT_ALLOWED,
                    f"허용되지 않는 함수입니다: {node.sql_name()}",
                )
            )
    return out


def _cte_names(root: exp.Expression) -> set[str]:
    return {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}


def _check_tables(
    root: exp.Expression, allowed_tables: Collection[str]
) -> list[Violation]:
    base = {t.lower() for t in allowed_tables}
    allowed = base | _cte_names(root)
    out: list[Violation] = []
    # 허용된 뷰/테이블과 같은 이름의 CTE는 서버가 뷰 정의를 CTE로 넣을 때 이름이 겹친다
    for name in sorted(_cte_names(root) & base):
        out.append(
            Violation(
                ViolationCode.TABLE_NOT_ALLOWED,
                f"CTE 이름이 허용된 뷰/테이블 이름과 같습니다: {name} (다른 이름을 쓰세요)",
            )
        )
    for table in root.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            out.append(
                Violation(
                    ViolationCode.TABLE_NOT_ALLOWED,
                    "테이블은 단순 이름이어야 합니다",
                )
            )
        elif table.args.get("db") or table.args.get("catalog"):
            out.append(
                Violation(
                    ViolationCode.TABLE_NOT_ALLOWED,
                    f"스키마를 붙인 테이블은 허용되지 않습니다: {table.sql()}",
                )
            )
        elif table.args.get("version"):
            out.append(
                Violation(
                    ViolationCode.TABLE_NOT_ALLOWED,
                    "과거 시점 조회(flashback, time travel)는 허용되지 않습니다",
                )
            )
        elif table.name.lower() not in allowed:
            out.append(
                Violation(
                    ViolationCode.TABLE_NOT_ALLOWED,
                    f"허용되지 않는 테이블(뷰)입니다: {table.name}",
                )
            )
    return out


def _iter_aliases(root: exp.Expression) -> Iterator[str]:
    for table in root.find_all(exp.Table):
        yield table.alias_or_name.lower()
    for sub in root.find_all(exp.Subquery):
        if sub.alias:
            yield sub.alias.lower()
    yield from _cte_names(root)


def _check_columns(root: exp.Expression) -> list[Violation]:
    aliases = set(_iter_aliases(root))
    out: list[Violation] = []
    for col in root.find_all(exp.Column):
        if col.args.get("db") or col.args.get("catalog"):
            out.append(
                Violation(
                    ViolationCode.COLUMN_NOT_ALLOWED,
                    f"과도하게 한정된 컬럼입니다: {col.sql()}",
                )
            )
        elif col.table and col.table.lower() not in aliases:
            out.append(
                Violation(
                    ViolationCode.COLUMN_NOT_ALLOWED,
                    f"알 수 없는 컬럼 한정자입니다: {col.table}",
                )
            )
    return out


def _check_column_existence(
    root: exp.Expression, dialect: str, columns: Mapping[str, Collection[str]]
) -> list[Violation]:
    # qualify()는 따옴표 없는 식별자를 소문자로 바꾸므로 스키마 키도 소문자로 맞춘다.
    schema = {
        view.lower(): {column.lower(): "text" for column in view_columns}
        for view, view_columns in columns.items()
    }
    try:
        qualify(
            root.copy(),
            schema=schema,
            dialect=dialect,
            validate_qualify_columns=True,
            quote_identifiers=False,
        )
    except Exception as e:  # noqa: BLE001 - 판단 불명은 거부한다
        return [
            Violation(
                ViolationCode.COLUMN_NOT_ALLOWED,
                f"컬럼을 확인하지 못했습니다 (없는 컬럼이거나 모호한 참조): {e}",
            )
        ]
    return []


def _check_query_shape(query: exp.Expression) -> list[Violation]:
    out: list[Violation] = []
    for w in query.find_all(exp.With):
        if w.args.get("recursive"):
            out.append(
                Violation(
                    ViolationCode.QUERY_SHAPE_NOT_ALLOWED,
                    "재귀 CTE는 지원하지 않습니다",
                )
            )
    for node in query.find_all(exp.Limit, exp.Offset, exp.Fetch):
        if node.parent is not query:
            out.append(
                Violation(
                    ViolationCode.QUERY_SHAPE_NOT_ALLOWED,
                    "LIMIT/OFFSET은 최상위 질의에만 쓸 수 있습니다",
                )
            )
    # FROM 없는 SELECT는 허용하지 않는다 (Oracle은 FROM dual이 필요하고 dual은 허용 목록에 없다).
    for select in query.find_all(exp.Select):
        if not select.args.get("from_"):
            out.append(
                Violation(
                    ViolationCode.QUERY_SHAPE_NOT_ALLOWED,
                    "모든 SELECT에는 FROM 절이 있어야 합니다",
                )
            )
    return out
