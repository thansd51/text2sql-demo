from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError


class MetadataError(Exception):
    """메타데이터를 읽거나 검사하다 실패했다. 시작 실패 사유로 쓴다.

    code는 영어 상수, message는 한국어다. 문제가 여러 건이면 한 번에 모아서 알린다.
    """

    code = "METADATA_INVALID"

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        self.message = f"메타데이터 오류 {len(self.problems)}건:\n" + "\n".join(
            f"- {problem}" for problem in self.problems
        )
        super().__init__(self.message)


def format_location(loc: Sequence[str | int]) -> str:
    """('views', 0, 'name') -> 'views[0].name'"""
    text = ""
    for part in loc:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else str(part)
    return text or "(최상위)"


def _describe(error: dict[str, Any]) -> str:
    kind = error["type"]
    ctx = error.get("ctx") or {}
    if kind == "missing":
        return "필수 항목이 없습니다"
    if kind == "extra_forbidden":
        return "알 수 없는 항목입니다 (철자를 확인하세요)"
    if kind == "literal_error":
        expected = str(ctx.get("expected", "")).replace("'", "").replace(" or ", ", ")
        return f"허용되지 않는 값입니다 (허용: {expected})"
    if kind == "string_type":
        return '문자열이어야 합니다 (숫자는 "100"처럼 따옴표로 감싸고, 값이 없으면 null이 아니라 ""로 적으세요)'
    if kind == "string_pattern_mismatch":
        pattern = str(ctx.get("pattern", "")).removeprefix("^").removesuffix("$")
        return f"형식이 올바르지 않습니다 (허용 패턴: {pattern})"
    if kind == "string_too_short":
        return "비어 있을 수 없습니다"
    if kind == "too_short":
        return f"항목이 {ctx.get('min_length', 1)}개 이상 필요합니다"
    if kind in ("list_type", "tuple_type"):
        return "목록이어야 합니다"
    if kind in ("dict_type", "model_type", "model_attributes_type"):
        return "객체(키: 값 묶음)여야 합니다"
    if kind == "value_error":
        return str(ctx.get("error", "값이 올바르지 않습니다"))
    # 영어 원문과 입력값은 노출하지 않는다 (입력값에 민감한 내용이 있을 수 있다)
    return f"값이 올바르지 않습니다 (오류 종류: {kind})"


def describe_validation_error(label: str, exc: ValidationError) -> list[str]:
    """Pydantic 오류를 '파일명: 위치: 사유' 형태의 한국어 문장 목록으로 바꾼다."""
    return [
        f"{label}: {format_location(error['loc'])}: {_describe(dict(error))}"
        for error in exc.errors(include_input=False, include_url=False)
    ]
