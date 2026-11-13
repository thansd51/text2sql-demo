import logging

from fastapi import APIRouter, Request

from text2sql.api.dependencies import GeneratorDep, RegistryDep, SettingsDep
from text2sql.api.errors import DatasourceNotFoundError, InvalidRequestError
from text2sql.api.request_id import request_id_of
from text2sql.api.schemas import (
    ErrorResponse,
    ReferenceResponse,
    TextToSqlRequest,
    TextToSqlResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


# 일반 def: FastAPI가 스레드 풀에서 실행하므로 LLM 호출이 이벤트 루프를 막지 않는다.
@router.post(
    "/text-to-sql",
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def text_to_sql(
    body: TextToSqlRequest,
    request: Request,
    registry: RegistryDep,
    generator: GeneratorDep,
    settings: SettingsDep,
) -> TextToSqlResponse:
    request_id = request_id_of(request)
    metadata = registry.get(body.datasource_id)
    if metadata is None:
        raise DatasourceNotFoundError()
    if len(body.question) > settings.max_question_length:
        raise InvalidRequestError(
            f"질문이 너무 깁니다 (최대 {settings.max_question_length}자)"
        )

    result = generator.run(body.question, metadata, request_id=request_id)
    # 질문 내용은 로그에 남기지 않는다.
    logger.info(
        "요청 처리 완료 (요청 %s, 데이터소스 %s, 상태 %s, 시도 %d회)",
        request_id,
        metadata.datasource.id,
        result.status.value,
        result.attempts,
    )
    return TextToSqlResponse(
        request_id=request_id,
        status=result.status.value,
        sql=result.sql,
        references=[
            ReferenceResponse(table=ref.table, columns=list(ref.columns))
            for ref in result.references
        ],
        metadata_version=metadata.metadata_version,
        message=result.reason.message if result.reason else None,
    )
