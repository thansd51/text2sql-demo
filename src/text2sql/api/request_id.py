import re
import uuid

from fastapi import Request

_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def request_id_of(request: Request) -> str:
    """서버가 uuid4를 발급한다. X-Request-Id 헤더가 안전한 형식이면 그 값을 쓴다."""
    cached = getattr(request.state, "request_id", None)
    if cached is not None:
        return cached
    header = request.headers.get("x-request-id", "")
    request_id = header if _SAFE_REQUEST_ID.fullmatch(header) else str(uuid.uuid4())
    request.state.request_id = request_id
    return request_id
