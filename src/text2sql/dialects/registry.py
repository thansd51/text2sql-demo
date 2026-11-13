from text2sql.dialects.base import BaseDialectAdapter, DialectAdapter
from text2sql.dialects.errors import UnsupportedDbTypeError
from text2sql.dialects.oracle import OracleAdapter
from text2sql.dialects.postgresql import PostgresqlAdapter

_ADAPTERS: dict[str, type[BaseDialectAdapter]] = {
    OracleAdapter.db_type: OracleAdapter,
    PostgresqlAdapter.db_type: PostgresqlAdapter,
}


def supported_db_types() -> tuple[str, ...]:
    return tuple(_ADAPTERS)


def get_adapter(db_type: str, db_version: str) -> DialectAdapter:
    try:
        adapter_class = _ADAPTERS[db_type]
    except KeyError:
        raise UnsupportedDbTypeError(
            f"지원하지 않는 DB 종류입니다: {db_type!r} "
            f"(지원: {', '.join(supported_db_types())})"
        ) from None
    return adapter_class(db_version)
