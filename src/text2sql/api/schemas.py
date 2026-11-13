"""HTTP 계약 (docs/design.md "API 계약", "응답과 상태")."""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints


class TextToSqlRequest(BaseModel):
    # 앞뒤 공백을 지우고 비어 있으면 거부한다. 최대 길이는 설정(max_question_length)으로 본다.
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    datasource_id: Annotated[str, StringConstraints(min_length=1)]


class ReferenceResponse(BaseModel):
    table: str
    columns: list[str]


class TextToSqlResponse(BaseModel):
    request_id: str
    status: Literal["OK", "REJECTED"]
    # REJECTED이면 null
    sql: str | None
    references: list[ReferenceResponse]
    metadata_version: str
    # REJECTED의 사유(한국어). OK이면 null.
    message: str | None = None


class DatasourceResponse(BaseModel):
    id: str
    name: str
    db_type: str
    db_version: str


class ErrorResponse(BaseModel):
    code: str  # 영어 상수
    message: str  # 한국어
