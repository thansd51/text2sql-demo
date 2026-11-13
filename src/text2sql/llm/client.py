"""LLM 클라이언트 인터페이스. 구현 교체가 필요한 지점이라 이 폴더 안에 둔다."""

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class LLMError(Exception):
    """LLM 호출 실패의 기반. code는 영어 상수, message는 한국어다."""

    code = "LLM_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LLMUnavailableError(LLMError):
    """LLM에 연결할 수 없거나 쓸 수 없는 응답을 받았다 (HTTP 503)."""

    code = "LLM_UNAVAILABLE"


class LLMTimeoutError(LLMError):
    """LLM이 제때 응답하지 않았다."""

    code = "LLM_TIMEOUT"


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class LLMClient(Protocol):
    def complete(self, messages: Sequence[ChatMessage]) -> str:
        """답변 텍스트를 돌려준다. 실패하면 LLMUnavailableError 또는 LLMTimeoutError."""
        ...
