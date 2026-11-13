"""앱 시작 때 만드는 것들 (docs/design.md: 레지스트리는 앱 시작 시 생성).

모듈을 import할 때는 아무것도 읽지 않는다. 파일 읽기와 검사는 이 함수들을 호출할 때만 한다.
"""

from urllib.parse import urlparse

from text2sql.config import Settings
from text2sql.dialects import DialectError, get_adapter
from text2sql.llm import AnthropicClient, LLMClient, OpenAICompatibleClient
from text2sql.pipeline import (
    SqlGenerator,
    check_example,
    check_prompt_budget,
    prompt_budget_tokens,
)
from text2sql.semantic import FileRepository, MetadataError, Registry, build_registry


def load_registry(settings: Settings) -> Registry:
    """파일에서 메타데이터를 읽어 레지스트리를 만든다. 문제가 있으면 MetadataError(시작 실패)."""
    repository = FileRepository(
        settings.datasources_dir,
        settings.semantic_dir,
        settings.profiles_dir,
        settings.examples_dir,
    )
    registry = build_registry(repository)
    _check_dialects(registry)
    _check_examples(registry)
    _check_prompt_budget(registry, settings)
    return registry


def _check_dialects(registry: Registry) -> None:
    """모든 데이터소스의 DB 종류와 버전을 어댑터가 받아들이는지 시작할 때 확인한다.

    요청을 받은 뒤에야 버전 오류가 드러나 500이 나는 일을 막는다.
    """
    problems: list[str] = []
    for metadata in registry.all_entries():
        datasource = metadata.datasource
        try:
            get_adapter(datasource.db_type, datasource.db_version)
        except DialectError as e:
            problems.append(f"datasources/{datasource.id}.json: {e.message}")
    if problems:
        raise MetadataError(problems)


def _check_examples(registry: Registry) -> None:
    """공통 예시가 모든 프로젝트의 테이블과 DB에서 통과하는지 시작할 때 확인한다.

    예시는 모든 프로젝트가 함께 쓰므로 하나가 틀리면 전부의 프롬프트가 오염된다.
    DB마다 문법이 다를 수 있어서 프로젝트(데이터소스)마다 따로 확인한다.
    """
    problems: list[str] = []
    for metadata in registry.all_entries():
        datasource = metadata.datasource
        adapter = get_adapter(datasource.db_type, datasource.db_version)
        for example in metadata.examples:
            for reason in check_example(example.sql, metadata, adapter):
                problems.append(
                    f"{datasource.id}({datasource.db_type} {datasource.db_version}): "
                    f"공통 예시 '{example.question}'가 통과하지 못했습니다: {reason}"
                )
    if problems:
        raise MetadataError(problems)


def _check_prompt_budget(registry: Registry, settings: Settings) -> None:
    """모든 프로젝트에서 질문이 가장 긴 경우에도 테이블 하나는 프롬프트에 담기는지 확인한다.

    컨텍스트 설정이 너무 작으면 요청을 받은 뒤에야 실패하지 않고 시작할 때 알린다.
    """
    budget = prompt_budget_tokens(settings.llm_context_tokens, settings.llm_max_tokens)
    problems: list[str] = []
    for metadata in registry.all_entries():
        datasource = metadata.datasource
        adapter = get_adapter(datasource.db_type, datasource.db_version)
        for reason in check_prompt_budget(
            metadata,
            adapter.prompt_rules(),
            budget,
            question_chars=settings.max_question_length,
            chars_per_token=settings.llm_chars_per_token,
        ):
            problems.append(f"{datasource.id}: {reason}")
    if problems:
        raise MetadataError(problems)


def max_tokens_field(settings: Settings) -> str:
    """답변 길이 제한을 보낼 요청 필드. OpenAI는 max_completion_tokens만 받는다."""
    if settings.llm_max_tokens_field != "auto":
        return settings.llm_max_tokens_field
    host = urlparse(settings.llm_base_url).hostname or ""
    return "max_completion_tokens" if host == "api.openai.com" else "max_tokens"


def create_llm(settings: Settings) -> LLMClient:
    """설정(TEXT2SQL_LLM_PROVIDER)에 맞는 LLM 클라이언트를 만든다."""
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    if settings.llm_provider == "anthropic":
        return AnthropicClient(
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
            effort=settings.llm_effort,
            use_fallbacks=settings.llm_anthropic_fallbacks,
            api_key=api_key,
        )
    return OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_tokens=settings.llm_max_tokens,
        max_tokens_field=max_tokens_field(settings),
        send_temperature=settings.llm_send_temperature,
        api_key=api_key,
    )


def create_generator(settings: Settings) -> SqlGenerator:
    llm = create_llm(settings)
    return SqlGenerator(
        llm,
        settings.max_repair_attempts,
        max_rows=settings.max_rows,
        prompt_budget_tokens=prompt_budget_tokens(
            settings.llm_context_tokens, settings.llm_max_tokens
        ),
        chars_per_token=settings.llm_chars_per_token,
    )
