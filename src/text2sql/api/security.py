"""접속 키 검사 (docs/design.md "API 계약"). 자체 로그인은 만들지 않는다.

요청 헤더 X-Access-Key가 설정한 접속 키와 같아야 한다. GET /health는 검사하지 않는다.
키 값은 로그나 응답에 싣지 않는다.
"""

import secrets
from typing import Annotated

from fastapi import Header

from text2sql.api.dependencies import SettingsDep
from text2sql.api.errors import UnauthorizedError


def require_access_key(
    settings: SettingsDep,
    x_access_key: Annotated[str | None, Header()] = None,
) -> None:
    if settings.auth_disabled:
        return
    expected = settings.access_key.get_secret_value() if settings.access_key else ""
    # 설정이 비어 있으면 모든 요청을 거부한다 (시작 시 검사를 거치지 않은 경우의 안전장치)
    if not expected or x_access_key is None:
        raise UnauthorizedError()
    # 시간차 공격을 피하려고 같은 시간에 비교한다
    if not secrets.compare_digest(x_access_key.encode(), expected.encode()):
        raise UnauthorizedError()
