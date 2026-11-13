class DialectError(Exception):
    """방언 처리 오류의 기반. code는 영어 상수, message는 한국어다."""

    code = "DIALECT_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedDbTypeError(DialectError):
    code = "UNSUPPORTED_DB_TYPE"


class InvalidDbVersionError(DialectError):
    code = "INVALID_DB_VERSION"


class RowLimitError(DialectError):
    code = "ROW_LIMIT_ERROR"
