"""접속 키 (X-Access-Key). 공개 배포에서 아무나 LLM을 호출하지 못하게 한다."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import GOOD, URL, HarnessFactory
from tests.fakes import FakeLLM
from tests.semantic.helpers import make_dirs
from text2sql.config import ConfigError, Settings, check_auth_settings
from text2sql.main import create_app
from text2sql.semantic import build_registry

KEY = "s3cret-access-key"
HEADER = {"X-Access-Key": KEY}
BODY = {"question": "상품 목록", "datasource_id": "p001"}


def secured(make_harness: HarnessFactory, *replies: str):
    return make_harness(*replies, auth_disabled=False, access_key=KEY)


# ---- 요청 검사 ----


def test_requests_without_a_key_are_rejected(make_harness: HarnessFactory) -> None:
    harness = secured(make_harness)

    for response in (
        harness.client.get("/api/v1/datasources"),
        harness.client.post(URL, json=BODY),
    ):
        assert response.status_code == 401
        assert response.json() == {
            "code": "UNAUTHORIZED",
            "message": "접속 키가 없거나 올바르지 않습니다",
        }
    assert harness.llm.prompts == []  # 거부된 요청은 LLM을 부르지 않는다


@pytest.mark.parametrize("wrong", ["", "wrong", KEY + "x", KEY.upper(), " " + KEY])
def test_a_wrong_key_is_rejected(make_harness: HarnessFactory, wrong: str) -> None:
    harness = secured(make_harness)

    response = harness.client.get(
        "/api/v1/datasources", headers={"X-Access-Key": wrong}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_the_right_key_is_accepted(make_harness: HarnessFactory) -> None:
    harness = secured(make_harness, GOOD)

    listed = harness.client.get("/api/v1/datasources", headers=HEADER)
    answered = harness.client.post(URL, json=BODY, headers=HEADER)

    assert listed.status_code == 200
    assert answered.status_code == 200
    assert answered.json()["status"] == "OK"


def test_health_needs_no_key(make_harness: HarnessFactory) -> None:
    harness = secured(make_harness)

    assert harness.client.get("/health").status_code == 200


def test_a_non_ascii_key_does_not_crash(make_harness: HarnessFactory) -> None:
    harness = secured(make_harness)

    response = harness.client.get(
        "/api/v1/datasources", headers={"X-Access-Key": "키".encode()}
    )

    assert response.status_code == 401


def test_an_unconfigured_key_rejects_everything(make_harness: HarnessFactory) -> None:
    # 시작 시 검사를 거치지 않은 경우의 안전장치: 키가 비어 있으면 아무 값도 통과하지 못한다
    harness = make_harness(auth_disabled=False)

    for header in ({}, {"X-Access-Key": ""}, {"X-Access-Key": "anything"}):
        assert (
            harness.client.get("/api/v1/datasources", headers=header).status_code == 401
        )


def test_with_auth_disabled_no_key_is_needed(make_harness: HarnessFactory) -> None:
    harness = make_harness(auth_disabled=True)

    assert harness.client.get("/api/v1/datasources").status_code == 200


def test_the_key_never_shows_up_in_responses_or_logs(
    make_harness: HarnessFactory, caplog: pytest.LogCaptureFixture
) -> None:
    harness = secured(make_harness)

    with caplog.at_level(logging.DEBUG):
        denied = harness.client.get(
            "/api/v1/datasources", headers={"X-Access-Key": "guess-12345"}
        )
        allowed = harness.client.get("/api/v1/datasources", headers=HEADER)

    assert "guess-12345" not in denied.text
    assert KEY not in allowed.text
    assert KEY not in caplog.text and "guess-12345" not in caplog.text
    assert KEY not in repr(harness.settings)  # SecretStr라서 repr에도 나오지 않는다


def test_the_built_frontend_is_served_without_a_key(
    tmp_path: Path, make_harness: HarnessFactory
) -> None:
    # 화면은 열리고, 키를 입력해야 API를 쓸 수 있다
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>화면</html>", encoding="utf-8")
    harness = make_harness(auth_disabled=False, access_key=KEY, frontend_dist_dir=dist)

    assert harness.client.get("/").status_code == 200
    assert harness.client.get("/api/v1/datasources").status_code == 401


# ---- 시작 시 검사 ----


@pytest.mark.parametrize("key", [None, "", "   "])
def test_startup_fails_without_an_access_key(key: str | None) -> None:
    settings = Settings(_env_file=None, auth_disabled=False, access_key=key)

    with pytest.raises(ConfigError) as info:
        check_auth_settings(settings)

    assert "TEXT2SQL_ACCESS_KEY" in info.value.message
    assert info.value.code == "CONFIG_INVALID"


def test_startup_passes_with_a_key_or_with_auth_disabled() -> None:
    check_auth_settings(Settings(_env_file=None, auth_disabled=False, access_key=KEY))
    check_auth_settings(Settings(_env_file=None, auth_disabled=True))


def test_the_app_refuses_to_start_without_a_key(tmp_path: Path) -> None:
    dirs = make_dirs(tmp_path)
    registry = build_registry(dirs.repository())
    app = create_app(
        Settings(_env_file=None, auth_disabled=False),
        registry=registry,
        llm=FakeLLM(),
    )

    with pytest.raises(ConfigError), TestClient(app):
        pass


def test_the_default_settings_require_a_key_when_the_environment_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 환경변수를 아무것도 주지 않은 배포는 키 없이 열리지 않는다 (기본값이 안전한 쪽이다)
    monkeypatch.delenv("TEXT2SQL_AUTH_DISABLED")

    settings = Settings(_env_file=None)

    assert settings.auth_disabled is False
    with pytest.raises(ConfigError):
        check_auth_settings(settings)


DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def test_api_docs_are_closed_when_a_key_is_required(
    make_harness: HarnessFactory,
) -> None:
    # 문서 경로는 접속 키 없이 열리므로, 키를 요구하는 배포에서는 존재하지 않아야 한다
    harness = secured(make_harness)

    for path in DOC_PATHS:
        assert harness.client.get(path).status_code == 404, path
        assert harness.client.get(path, headers=HEADER).status_code == 404, path


def test_api_docs_stay_open_for_local_development(make_harness: HarnessFactory) -> None:
    harness = make_harness(auth_disabled=True)

    for path in DOC_PATHS:
        assert harness.client.get(path).status_code == 200, path


def test_source_and_secret_files_are_never_served(
    tmp_path: Path, make_harness: HarnessFactory
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>화면</html>", encoding="utf-8")
    harness = make_harness(auth_disabled=False, access_key=KEY, frontend_dist_dir=dist)

    for path in ("/.env", "/pyproject.toml", "/src/text2sql/config.py", "/../.env"):
        response = harness.client.get(path)
        assert "TEXT2SQL" not in response.text, path
        assert "pydantic" not in response.text, path
