from collections.abc import Sequence

import httpx2

from text2sql.llm.client import ChatMessage, LLMTimeoutError, LLMUnavailableError


class OpenAICompatibleClient:
    """OpenAI 호환 chat completions API(llama.cpp 등)용 클라이언트."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        max_tokens_field: str = "max_tokens",
        send_temperature: bool = True,
        api_key: str | None = None,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._max_tokens = max_tokens
        self._max_tokens_field = max_tokens_field
        self._send_temperature = send_temperature
        # 키는 헤더에만 쓰고 로그나 오류 메시지에 싣지 않는다
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx2.Client(
            timeout=timeout_seconds, transport=transport, headers=headers
        )

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [m.model_dump() for m in messages],
            self._max_tokens_field: self._max_tokens,
        }
        if self._send_temperature:
            payload["temperature"] = 0
        try:
            response = self._client.post(self._url, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except httpx2.TimeoutException as e:
            raise LLMTimeoutError("LLM 응답 시간이 초과되었습니다") from e
        except httpx2.HTTPStatusError as e:
            raise LLMUnavailableError(
                f"LLM 호출에 실패했습니다 ({_describe_status(e.response)})"
            ) from e
        except (httpx2.HTTPError, ValueError, LookupError, TypeError) as e:
            raise LLMUnavailableError(
                f"LLM 호출에 실패했습니다 ({type(e).__name__})"
            ) from e
        if not isinstance(content, str):
            raise LLMUnavailableError("LLM 응답에 텍스트 내용이 없습니다")
        return content


def _describe_status(response: httpx2.Response) -> str:
    """상태코드와 서버가 알려 준 오류 종류만 돌려준다 (예: HTTP 401, invalid_api_key).

    응답 본문 전체는 싣지 않는다. 키의 일부가 에코될 수 있고 입력 내용이 들어 있을 수 있다.
    """
    kind = ""
    try:
        error = response.json().get("error")
        if isinstance(error, dict):
            raw = error.get("code") or error.get("type")
            if isinstance(raw, str) and raw.replace("_", "").replace("-", "").isalnum():
                kind = f", {raw[:60]}"
    except (ValueError, AttributeError):
        pass
    return f"HTTP {response.status_code}{kind}"
