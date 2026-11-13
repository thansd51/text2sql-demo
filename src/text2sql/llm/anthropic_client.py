"""Claude(Anthropic) 클라이언트. 공식 SDK의 Messages API를 쓴다.

OpenAI 호환 클라이언트(openai_compatible.py)와 같은 LLMClient 인터페이스라서 파이프라인은
어느 쪽을 쓰는지 모른다. 설정(TEXT2SQL_LLM_PROVIDER)으로 고른다.

Claude Opus 5.5 기준의 주의점:
- temperature 같은 샘플링 값을 보내면 400이라 보내지 않는다.
- thinking을 끌 수 없다. 응답 속도를 위해 effort를 낮게(기본 low) 둔다. 생각에 쓰는 토큰도
  max_tokens에 들어가므로 max_tokens는 넉넉히 잡아야 한다.
- 모델이 요청을 거절(refusal)하면 서버측 fallbacks로 다른 모델이 이어받는다 (기본 켬).
"""

from collections.abc import Sequence

import anthropic
import httpx2

from text2sql.llm.client import ChatMessage, LLMTimeoutError, LLMUnavailableError

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicClient:
    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        effort: str = "low",
        use_fallbacks: bool = True,
        max_retries: int = 2,
        api_key: str | None = None,
        http_client: httpx2.Client | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._effort = effort
        self._use_fallbacks = use_fallbacks
        # api_key가 없으면 SDK가 환경(ANTHROPIC_API_KEY 등)에서 찾는다. 키는 로그에 싣지 않는다.
        # 429와 5xx, 연결 오류는 SDK가 알아서 다시 시도한다 (기본 2번)
        self._client = anthropic.Anthropic(
            api_key=api_key or None,
            timeout=timeout_seconds,
            max_retries=max_retries,
            http_client=http_client,
        )

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]
        request: dict[str, object] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": turns,
            "output_config": {"effort": self._effort},
        }
        if system:
            request["system"] = system
        if self._use_fallbacks:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        try:
            response = self._client.beta.messages.create(**request)  # type: ignore[arg-type]
        except anthropic.AuthenticationError as e:
            raise LLMUnavailableError(_describe(e)) from e
        except anthropic.PermissionDeniedError as e:
            raise LLMUnavailableError(_describe(e)) from e
        except anthropic.NotFoundError as e:
            raise LLMUnavailableError(_describe(e)) from e
        except anthropic.RateLimitError as e:
            raise LLMUnavailableError(_describe(e)) from e
        except anthropic.APIStatusError as e:
            raise LLMUnavailableError(_describe(e)) from e
        except anthropic.APITimeoutError as e:
            # APITimeoutError는 APIConnectionError의 하위라서 먼저 잡는다
            raise LLMTimeoutError("LLM 응답 시간이 초과되었습니다") from e
        except anthropic.APIConnectionError as e:
            raise LLMUnavailableError("LLM에 연결하지 못했습니다") from e

        if response.stop_reason == "refusal":
            raise LLMUnavailableError("모델이 요청을 거절했습니다 (refusal)")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            reason = response.stop_reason or "알 수 없음"
            raise LLMUnavailableError(
                f"LLM 응답에 텍스트 내용이 없습니다 (중단 사유: {reason}). "
                "TEXT2SQL_LLM_MAX_TOKENS가 너무 작지 않은지 확인하세요"
            )
        return text


def _describe(error: anthropic.APIStatusError) -> str:
    """상태코드와 오류 종류만 알린다. 응답 본문 전체는 싣지 않는다."""
    kind = ""
    body = error.body
    if isinstance(body, dict):
        detail = body.get("error")
        raw = detail.get("type") if isinstance(detail, dict) else None
        if isinstance(raw, str) and raw.replace("_", "").isalnum():
            kind = f", {raw[:60]}"
    return f"LLM 호출에 실패했습니다 (HTTP {error.status_code}{kind})"
