"""SQL이 참조하는 테이블과 컬럼을 sqlglot으로 뽑는다 (docs/design.md "응답과 상태").

qualify()로 별칭과 `*`를 풀어 낸 뒤, 각 컬럼이 어느 테이블에서 왔는지 따라간다.
CTE와 FROM 절 하위 질의(파생 테이블)는 테이블이 아니므로 건너뛰고, 그 안쪽 질의에서
실제 테이블 컬럼을 센다. 이미 1차 검증(같은 qualify)을 통과한 SQL에 쓰는 것을 전제로 한다.

식별자는 먼저 방언 규칙으로 정규화한 다음 모두 소문자로 통일해서 방언에 의존하지 않는
qualify로 처리한다. Oracle 방언으로 직접 qualify하면 sqlglot이 하위 질의 안의 일부
컬럼을 한정하지 않고 지나치는 경우가 있어서(컬럼이 응답에서 빠진다) 이 방식을 쓴다.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope


@dataclass(frozen=True)
class Reference:
    table: str
    columns: tuple[str, ...]  # 테이블에 선언된 순서


def extract_references(
    sql: str, *, dialect: str, columns_by_table: Mapping[str, Collection[str]]
) -> tuple[Reference, ...]:
    """사용한 테이블과 그 컬럼. 테이블 이름 순서로 돌려준다."""
    tables = {table.lower(): table for table in columns_by_table}
    declared = {
        table.lower(): list(columns) for table, columns in columns_by_table.items()
    }
    schema = {
        table: {column.lower(): "text" for column in columns}
        for table, columns in declared.items()
    }

    tree = normalize_identifiers(sqlglot.parse_one(sql, read=dialect), dialect=dialect)
    for identifier in tree.find_all(exp.Identifier):
        identifier.set("this", identifier.name.lower())
        identifier.set("quoted", False)
    root = qualify(tree, schema=schema, quote_identifiers=False)

    used: dict[str, set[str]] = {}
    for scope in traverse_scope(root):
        for source in scope.sources.values():
            table = _table_of(source, tables)
            if table is not None:
                used.setdefault(table, set())
        for column in scope.columns:
            table = _table_of(_resolve(scope, column.table), tables)
            if table is not None:
                used.setdefault(table, set()).add(column.name.lower())

    return tuple(
        Reference(
            table=tables[table],
            columns=tuple(c for c in declared[table] if c.lower() in used[table]),
        )
        for table in sorted(used)
    )


def extract_table_names(sql: str, *, dialect: str) -> frozenset[str]:
    """SQL이 FROM/JOIN으로 쓰는 실제 테이블 이름(대문자). CTE 이름은 뺀다.

    예시가 어느 테이블을 쓰는지 알아서 프롬프트에서 걸러 내는 데 쓴다. 파싱할 수 없으면
    빈 집합을 돌려준다 (어느 테이블인지 모르는 예시는 쓰지 않는다).
    """
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except sqlglot.errors.SqlglotError:
        return frozenset()
    ctes = {cte.alias_or_name.upper() for cte in tree.find_all(exp.CTE)}
    return frozenset(
        table.name.upper()
        for table in tree.find_all(exp.Table)
        if table.name and table.name.upper() not in ctes
    )


def _resolve(scope: Scope, alias: str) -> exp.Expression | Scope | None:
    """별칭이 가리키는 원본. 상관 하위 질의의 바깥 별칭은 부모 범위에서 찾는다."""
    current: Scope | None = scope
    while current is not None:
        if alias in current.sources:
            return current.sources[alias]
        current = current.parent
    return None


def _table_of(source: object, tables: Mapping[str, str]) -> str | None:
    if isinstance(source, exp.Table) and source.name.lower() in tables:
        return source.name.lower()
    return None
