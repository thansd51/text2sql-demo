import json
import re
from collections.abc import Callable

import httpx2
import pytest

from text2sql.llm import (
    ChatMessage,
    LLMClient,
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    OpenAICompatibleClient,
)

HANGUL = re.compile(r"[가-힣]")
MESSAGES = [
    ChatMessage(role="system", content="규칙"),
    ChatMessage(role="user", content="질문"),
]


def make_client(
    handler: Callable[[httpx2.Request], httpx2.Response],
    *,
    base_url: str = "http://llm.test/v1",
    api_key: str | None = None,
) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url=base_url,
        model="test-model",
        timeout_seconds=5,
        max_tokens=128,
        api_key=api_key,
        transport=httpx2.MockTransport(handler),
    )


def ok_response(content: object = "SELECT 1") -> httpx2.Response:
    return httpx2.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_returns_reply_text_and_sends_expected_payload() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return ok_response("SELECT a FROM v")

    reply = make_client(handler).complete(MESSAGES)

    assert reply == "SELECT a FROM v"
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["body"] == {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "규칙"},
            {"role": "user", "content": "질문"},
        ],
        "temperature": 0,
        "max_tokens": 128,
    }
    assert seen["auth"] is None


def test_trailing_slash_in_base_url_is_ignored() -> None:
    urls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        urls.append(str(request.url))
        return ok_response()

    make_client(handler, base_url="http://llm.test/v1/").complete(MESSAGES)

    assert urls == ["http://llm.test/v1/chat/completions"]


def test_api_key_is_sent_as_bearer_header_only_when_given() -> None:
    headers: list[str | None] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        headers.append(request.headers.get("authorization"))
        return ok_response()

    make_client(handler, api_key="k-123").complete(MESSAGES)

    assert headers == ["Bearer k-123"]


def test_timeout_becomes_llm_timeout_error_in_korean() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("느림", request=request)

    with pytest.raises(LLMTimeoutError) as info:
        make_client(handler).complete(MESSAGES)

    assert info.value.code == "LLM_TIMEOUT"
    assert HANGUL.search(info.value.message)


@pytest.mark.parametrize(
    "handler_result",
    [
        httpx2.Response(500, text="boom"),
        httpx2.Response(401, json={"error": "unauthorized"}),
        httpx2.Response(200, text="이건 JSON이 아님"),
        httpx2.Response(200, json={"choices": []}),
        httpx2.Response(200, json={"no_choices": True}),
        httpx2.Response(200, json={"choices": [{"message": {}}]}),
        httpx2.Response(200, json={"choices": [{"message": {"content": None}}]}),
        httpx2.Response(200, json={"choices": [{"message": {"content": 123}}]}),
        httpx2.Response(200, json=["list"]),
    ],
)
def test_bad_responses_become_llm_unavailable_error(
    handler_result: httpx2.Response,
) -> None:
    with pytest.raises(LLMUnavailableError) as info:
        make_client(lambda request: handler_result).complete(MESSAGES)

    assert info.value.code == "LLM_UNAVAILABLE"
    assert HANGUL.search(info.value.message)


def test_connection_failure_becomes_llm_unavailable_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("연결 실패", request=request)

    with pytest.raises(LLMUnavailableError) as info:
        make_client(handler).complete(MESSAGES)

    assert HANGUL.search(info.value.message)


def test_error_messages_do_not_leak_the_api_key_or_body() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, text="서버 내부 정보 SECRET-BODY")

    with pytest.raises(LLMUnavailableError) as info:
        make_client(handler, api_key="k-SECRET").complete(MESSAGES)

    assert "k-SECRET" not in info.value.message
    assert "SECRET-BODY" not in info.value.message


def test_llm_errors_share_one_base_class_and_client_matches_the_protocol() -> None:
    assert issubclass(LLMTimeoutError, LLMError)
    assert issubclass(LLMUnavailableError, LLMError)
    client: LLMClient = make_client(lambda request: ok_response())
    assert client.complete(MESSAGES) == "SELECT 1"


# ---- 답변 길이 제한 필드 (OpenAI는 max_completion_tokens만 받는다) ----


def sent_payload(max_tokens_field: str | None) -> dict:
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return ok_response()

    kwargs = {} if max_tokens_field is None else {"max_tokens_field": max_tokens_field}
    OpenAICompatibleClient(
        base_url="http://llm.test/v1",
        model="test-model",
        timeout_seconds=5,
        max_tokens=128,
        transport=httpx2.MockTransport(handler),
        **kwargs,
    ).complete(MESSAGES)
    return seen


def test_the_default_field_is_max_tokens() -> None:
    payload = sent_payload(None)

    assert payload["max_tokens"] == 128
    assert "max_completion_tokens" not in payload


def test_max_completion_tokens_can_be_used_instead() -> None:
    payload = sent_payload("max_completion_tokens")

    assert payload["max_completion_tokens"] == 128
    assert "max_tokens" not in payload


@pytest.mark.parametrize(
    ("base_url", "configured", "expected"),
    [
        ("https://api.openai.com/v1", "auto", "max_completion_tokens"),
        ("https://api.openai.com/v1/", "auto", "max_completion_tokens"),
        ("http://localhost:8083/v1", "auto", "max_tokens"),
        ("http://localhost:11434/v1", "auto", "max_tokens"),  # Ollama
        ("https://api.openai.com.evil.test/v1", "auto", "max_tokens"),
        ("http://localhost:8083/v1", "max_completion_tokens", "max_completion_tokens"),
        ("https://api.openai.com/v1", "max_tokens", "max_tokens"),
    ],
)
def test_the_token_field_is_chosen_from_the_server_address(
    base_url: str, configured: str, expected: str
) -> None:
    from text2sql.config import Settings
    from text2sql.startup import max_tokens_field

    settings = Settings(
        _env_file=None, llm_base_url=base_url, llm_max_tokens_field=configured
    )

    assert max_tokens_field(settings) == expected


def test_temperature_is_zero_by_default_and_can_be_left_out() -> None:
    seen: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return ok_response()

    for send in (True, False):
        OpenAICompatibleClient(
            base_url="http://llm.test/v1",
            model="m",
            timeout_seconds=5,
            max_tokens=8,
            send_temperature=send,
            transport=httpx2.MockTransport(handler),
        ).complete(MESSAGES)

    assert seen[0]["temperature"] == 0
    assert "temperature" not in seen[1]


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            401,
            {"error": {"code": "invalid_api_key", "message": "sk-abc...xyz"}},
            "HTTP 401, invalid_api_key",
        ),
        (
            404,
            {"error": {"type": "invalid_request_error", "code": "model_not_found"}},
            "HTTP 404, model_not_found",
        ),
        (
            429,
            {"error": {"type": "insufficient_quota"}},
            "HTTP 429, insufficient_quota",
        ),
        (500, "not json", "HTTP 500)"),
        (400, {"error": {"code": "has spaces and sk-secret"}}, "HTTP 400)"),
    ],
)
def test_http_errors_report_the_status_and_kind_but_not_the_body(
    status: int, body: object, expected: str
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if isinstance(body, str):
            return httpx2.Response(status, text=body)
        return httpx2.Response(status, json=body)

    with pytest.raises(LLMUnavailableError) as info:
        make_client(handler, api_key="k-SECRET").complete(MESSAGES)

    message = str(info.value)
    assert expected in message
    assert "sk-" not in message and "k-SECRET" not in message
    assert HANGUL.search(message)
