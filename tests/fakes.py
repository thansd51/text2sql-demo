from collections.abc import Sequence

from text2sql.llm import ChatMessage


class FakeLLM:
    """정해 둔 답변을 순서대로 돌려주고, 받은 프롬프트를 모두 기록한다.

    Exception 인스턴스를 넣으면 그 차례에 그 예외를 던진다. 실제 LLM은 호출하지 않는다.
    """

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[ChatMessage, ...]] = []

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.prompts.append(tuple(messages))
        if not self.replies:
            raise AssertionError("준비한 답변보다 LLM 호출이 많습니다")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
