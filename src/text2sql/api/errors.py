"""오류 응답: { code: 영어 상수, message: 한국어 } (docs/design.md "API 계약").

HTTP 상태는 설계서를 따른다: 잘못된 요청과 미등록 datasource_id는 400, LLM 사용 불가는 503.
예상하지 못한 오류는 상세를 숨기고 500으로 같은 형식의 본문을 돌려준다.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from text2sql.llm import LLMTimeoutError, LLMUnavailableError

logger = logging.getLogger(__name__)

INVALID_REQUEST = "INVALID_REQUEST"
DATASOURCE_NOT_FOUND = "DATASOURCE_NOT_FOUND"
UNAUTHORIZED = "UNAUTHORIZED"
LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
LLM_TIMEOUT = "LLM_TIMEOUT"
INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(Exception):
    """요청 처리 중 응답으로 바꿀 오류. message는 한국어다."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class InvalidRequestError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(400, INVALID_REQUEST, message)


class DatasourceNotFoundError(ApiError):
    def __init__(self) -> None:
        super().__init__(400, DATASOURCE_NOT_FOUND, "등록되지 않은 데이터소스입니다")


class UnauthorizedError(ApiError):
    def __init__(self) -> None:
        super().__init__(401, UNAUTHORIZED, "접속 키가 없거나 올바르지 않습니다")


def _body(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"code": code, "message": message}
    )


def _api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _body(exc.status_code, exc.code, exc.message)


def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    if any(error["type"] == "json_invalid" for error in exc.errors()):
        return _body(400, INVALID_REQUEST, "요청 본문이 올바른 JSON 형식이 아닙니다")
    # 어느 항목이 문제인지만 알리고 입력값은 되돌려 주지 않는다.
    fields = sorted(
        {
            ".".join(str(part) for part in error["loc"] if part != "body") or "(본문)"
            for error in exc.errors()
        }
    )
    return _body(
        400,
        INVALID_REQUEST,
        f"요청 형식이 올바르지 않습니다. 확인할 항목: {', '.join(fields)}",
    )


def _llm_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logger.error("LLM을 사용할 수 없습니다: %s", exc)
    return _body(503, LLM_UNAVAILABLE, "LLM을 사용할 수 없습니다")


def _llm_timeout(request: Request, exc: Exception) -> JSONResponse:
    logger.error("LLM 응답 시간이 초과되었습니다: %s", exc)
    return _body(503, LLM_TIMEOUT, "LLM 응답 시간이 초과되었습니다")


def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    logger.error(
        "요청 처리 중 예상하지 못한 오류가 발생했습니다 (요청 %s): %s",
        request_id,
        type(exc).__name__,
        exc_info=exc,
    )
    return _body(500, INTERNAL_ERROR, "서버 내부 오류입니다")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(LLMUnavailableError, _llm_unavailable)
    app.add_exception_handler(LLMTimeoutError, _llm_timeout)
    app.add_exception_handler(Exception, _unexpected)
