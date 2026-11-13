from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# 기본 경로는 이 파일 위치 기준이다. 실행 위치(cwd)에 의존하지 않는다.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TEXT2SQL_", env_file=".env", extra="ignore"
    )

    app_name: str = "text2sql"
    # 접속 키 (요청 헤더 X-Access-Key). 비밀 값이므로 환경변수로만 준다.
    # 공개 배포에서는 필수다. 설정하지 않으면 서버가 시작하지 않는다.
    access_key: SecretStr | None = None
    # 로컬 개발에서만 true로 둔다. 접속 키 검사를 끈다 (공개 배포에서는 쓰지 않는다).
    auth_disabled: bool = False
    # openai: OpenAI 호환 API(OpenAI, Ollama, llama.cpp). anthropic: Claude 공식 API.
    # anthropic이면 llm_base_url은 쓰지 않는다.
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_base_url: str = "http://localhost:8084/v1"
    llm_model: str = "default"
    llm_timeout_seconds: float = 120.0
    llm_max_tokens: int = 512
    # 답변 길이 제한을 보내는 요청 필드 이름. auto면 OpenAI(api.openai.com)에는
    # max_completion_tokens를, 그 밖의 서버(llama.cpp, Ollama 등)에는 max_tokens를 쓴다.
    # 최신 OpenAI 모델은 max_tokens를 받지 않는다.
    llm_max_tokens_field: Literal["auto", "max_tokens", "max_completion_tokens"] = (
        "auto"
    )
    # 모델이 한 번에 받을 수 있는 토큰(프롬프트 + 답변). 서버가 프롬프트 크기를 여기에 맞춘다.
    # Ollama는 num_ctx와 같은 값으로 맞춘다 (서버 쪽 설정이라 이 값만 바꿔서는 늘어나지 않는다).
    llm_context_tokens: int = Field(default=16384, ge=1)
    # 프롬프트 글자 수로 토큰 수를 어림할 때 쓰는 값. 한국어가 많아 넉넉하게 잡는다.
    # 모델의 토크나이저가 한글을 더 잘게 쪼개면 낮춘다.
    llm_chars_per_token: float = Field(default=1.8, gt=0)
    # anthropic 전용. 생각에 쓰는 깊이. 낮을수록 빠르고 싸다 (SQL 생성에는 low로 시작한다).
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    # anthropic 전용. 모델이 요청을 거절하면 다른 모델이 이어받게 한다. 모델이 지원하지
    # 않으면 false로 둔다.
    llm_anthropic_fallbacks: bool = True
    # 요청에 temperature 0을 실어 보낼지. 일부 모델(OpenAI 추론 계열 등)은 기본값 외의
    # temperature를 거부하므로 그런 모델에서는 false로 둔다.
    llm_send_temperature: bool = True
    # 비밀 값이므로 환경변수로만 준다 (TEXT2SQL_LLM_API_KEY). 필요 없으면 비워 둔다.
    llm_api_key: SecretStr | None = None
    # 1차 검증에 실패했을 때 오류를 넣어 다시 시도하는 최대 횟수
    max_repair_attempts: int = Field(default=2, ge=0)
    # 질문 최대 글자 수. 넘으면 400으로 거부한다.
    max_question_length: int = Field(default=500, ge=1)
    # 결과 행 수 상한. 최종 SQL에 강제로 걸린다 (Oracle은 ROWNUM, PostgreSQL은 LIMIT).
    max_rows: int = Field(default=1000, ge=1)
    datasources_dir: Path = _PROJECT_ROOT / "datasources"
    semantic_dir: Path = _PROJECT_ROOT / "semantic"
    profiles_dir: Path = _PROJECT_ROOT / "profiles"
    # 제품 공통 질문-SQL 예시 (examples/<제품>.yml). 모든 프로젝트가 함께 쓴다.
    examples_dir: Path = _PROJECT_ROOT / "examples"
    # React 빌드 결과(npm run build). 폴더가 있으면 FastAPI가 같은 출처로 제공한다.
    frontend_dist_dir: Path = _PROJECT_ROOT / "frontend" / "dist"


class ConfigError(Exception):
    """설정이 잘못돼 서버를 시작할 수 없다. message는 한국어다."""

    code = "CONFIG_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def check_auth_settings(settings: Settings) -> None:
    """접속 키가 없으면 시작하지 않는다 (키 없이 공개되는 일을 막는다)."""
    if settings.auth_disabled:
        return
    key = settings.access_key.get_secret_value() if settings.access_key else ""
    if not key.strip():
        raise ConfigError(
            "접속 키가 설정되지 않았습니다. 환경변수 TEXT2SQL_ACCESS_KEY를 설정하세요 "
            "(로컬 개발에서만 TEXT2SQL_AUTH_DISABLED=true로 끌 수 있습니다)"
        )


def get_settings() -> Settings:
    return Settings()
