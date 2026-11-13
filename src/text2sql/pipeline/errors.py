class PipelineError(Exception):
    """서버가 만든 SQL을 조립하다 실패했다. 질문이 아니라 서버 쪽 문제다 (HTTP 500).

    code는 영어 상수, message는 한국어다. 거부된 SQL 본문은 담지 않는다.
    """

    code = "PIPELINE_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FinalValidationError(PipelineError):
    """행 제한까지 건 SQL이 최종 검증을 통과하지 못했다."""

    code = "FINAL_VALIDATION_FAILED"


class PromptTooLargeError(PipelineError):
    """테이블 하나만으로도 프롬프트가 모델의 컨텍스트 예산을 넘는다 (설정 문제)."""

    code = "PROMPT_TOO_LARGE"
