"""Claude(Anthropic) 클라이언트. 실제 API는 호출하지 않고 가짜 전송 계층을 쓴다."""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from text2sql.config import Settings
from text2sql.llm import (
    AnthropicClient,
    ChatMessage,
    LLMClient,
    LLMTimeoutError,
    LLMUnavailableError,
    OpenAICompatibleClient,
)
from text2sql.startup import create_llm

HANGUL = re.compile(r"[가-힣]")
MESSAGES = [
    ChatMessage(role="system", content="규칙 하나"),
    ChatMessage(role="system", content="규칙 둘"),
    ChatMessage(role="user", content="질문"),
]


def message(
    text: str | None = "SELECT 1", stop_reason: str = "end_turn"
) -> httpx2.Response:
    content = [] if text is None else [{"type": "text", "text": text}]
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )


def make_client(
    handler: Callable[[httpx2.Request], httpx2.Response], **kwargs: Any
) -> AnthropicClient:
    options: dict[str, Any] = {
        "model": "claude-opus-5-5",
        "timeout_seconds": 5,
        "max_tokens": 4096,
        "api_key": "k-SECRET",
        "http_client": httpx2.Client(transport=httpx2.MockTransport(handler)),
    }
    options.update(kwargs)
    return AnthropicClient(**options)


def captured(**kwargs: Any) -> tuple[dict[str, Any], httpx2.Request]:
    seen: dict[str, Any] = {}
    request_box: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        request_box.append(request)
        return message()

    make_client(handler, **kwargs).complete(MESSAGES)
    return seen, request_box[0]


def test_it_satisfies_the_llm_client_interface() -> None:
    client: LLMClient = make_client(lambda request: message())

    assert client.complete(MESSAGES) == "SELECT 1"


def test_system_messages_become_the_top_level_system_field() -> None:
    body, _ = captured()

    assert body["system"] == "규칙 하나\n\n규칙 둘"
    assert body["messages"] == [{"role": "user", "content": "질문"}]
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 4096


def test_no_sampling_parameters_are_sent() -> None:
    # Claude Opus 5.5는 temperature/top_p/top_k를 받지 않는다 (400)
    body, _ = captured()

    assert not {"temperature", "top_p", "top_k"} & set(body)
    assert "thinking" not in body  # thinking은 끌 수 없고 기본값(적응형)을 쓴다


def test_effort_defaults_to_low_and_can_be_changed() -> None:
    assert captured()[0]["output_config"] == {"effort": "low"}
    assert captured(effort="high")[0]["output_config"] == {"effort": "high"}


def test_refusal_fallbacks_are_on_by_default_and_can_be_turned_off() -> None:
    body, request = captured()
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]

    body, request = captured(use_fallbacks=False)
    assert "fallbacks" not in body
    assert "server-side-fallback" not in request.headers.get("anthropic-beta", "")


def test_the_key_goes_in_the_header_only() -> None:
    body, request = captured()

    assert request.headers["authorization"] == "Bearer k-SECRET"
    assert "k-SECRET" not in json.dumps(body)


def test_without_a_system_message_the_field_is_left_out() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return message()

    make_client(handler).complete([ChatMessage(role="user", content="질문")])

    assert "system" not in seen


def test_text_blocks_are_joined_and_other_blocks_are_ignored() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "x"},
                    {"type": "text", "text": "SELECT A"},
                    {"type": "text", "text": " FROM T"},
                ],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    assert make_client(handler).complete(MESSAGES) == "SELECT A FROM T"


# ---- 오류 ----


def error_response(
    status: int, kind: str
) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda request: httpx2.Response(
        status,
        json={
            "type": "error",
            "error": {
                "type": kind,
                "message": "본문에 sk-ant-secret 같은 값이 있을 수 있다",
            },
        },
    )


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, "authentication_error"),
        (403, "permission_error"),
        (404, "not_found_error"),
        (400, "invalid_request_error"),
        (429, "rate_limit_error"),
    ],
)
def test_http_errors_become_llm_unavailable_with_status_and_kind_only(
    status: int, kind: str
) -> None:
    client = make_client(error_response(status, kind), max_retries=0)

    with pytest.raises(LLMUnavailableError) as info:
        client.complete(MESSAGES)

    text = info.value.message
    assert f"HTTP {status}, {kind}" in text
    assert "sk-ant" not in text and "k-SECRET" not in text
    assert HANGUL.search(text)


def test_a_timeout_becomes_llm_timeout() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("느림", request=request)

    with pytest.raises(LLMTimeoutError):
        make_client(handler, max_retries=0).complete(MESSAGES)


def test_a_connection_failure_becomes_llm_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("연결 실패", request=request)

    with pytest.raises(LLMUnavailableError) as info:
        make_client(handler, max_retries=0).complete(MESSAGES)

    assert "연결하지 못했습니다" in info.value.message


def test_a_refusal_is_reported_in_korean() -> None:
    client = make_client(lambda request: message(text=None, stop_reason="refusal"))

    with pytest.raises(LLMUnavailableError) as info:
        client.complete(MESSAGES)

    assert "거절" in info.value.message


def test_an_answer_cut_off_before_any_text_points_at_max_tokens() -> None:
    client = make_client(lambda request: message(text=None, stop_reason="max_tokens"))

    with pytest.raises(LLMUnavailableError) as info:
        client.complete(MESSAGES)

    assert "TEXT2SQL_LLM_MAX_TOKENS" in info.value.message
    assert "max_tokens" in info.value.message


# ---- 설정으로 고른다 ----


def test_the_provider_setting_picks_the_client() -> None:
    openai = create_llm(Settings(_env_file=None))
    claude = create_llm(
        Settings(_env_file=None, llm_provider="anthropic", llm_model="claude-opus-5-5")
    )

    assert isinstance(openai, OpenAICompatibleClient)
    assert isinstance(claude, AnthropicClient)


def test_the_default_provider_stays_openai_compatible() -> None:
    assert Settings(_env_file=None).llm_provider == "openai"


def test_an_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, llm_provider="gemini")  # type: ignore[arg-type]
