import pytest


@pytest.fixture(autouse=True)
def _auth_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """시험은 접속 키 없이 돌린다. 접속 키를 시험하는 곳은 설정을 직접 넘겨 덮어쓴다."""
    monkeypatch.setenv("TEXT2SQL_AUTH_DISABLED", "true")
    # 개발자 PC의 환경변수가 시험 결과를 바꾸지 않게 한다
    for name in ("TEXT2SQL_ACCESS_KEY", "TEXT2SQL_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
