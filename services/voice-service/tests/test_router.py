import asyncio
from types import SimpleNamespace

import pytest
from voice_service.router import HaikuRouter, RouterError


class _FakeToolUseBlock(SimpleNamespace):
    pass


class _FakeMessages:
    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _tool_response(router_class: str):
    return SimpleNamespace(
        content=[_FakeToolUseBlock(type="tool_use", name="classify_utterance", input={"router_class": router_class})]
    )


def test_classify_returns_the_tool_call_result():
    fake = _FakeMessages(_tool_response("new_intent"))
    router = HaikuRouter(client=fake)

    result = asyncio.run(router.classify("clear my morning, I'm sick"))

    assert result == "new_intent"
    assert fake.calls[0]["tool_choice"] == {"type": "tool", "name": "classify_utterance"}


def test_classify_passes_active_task_context():
    fake = _FakeMessages(_tool_response("modify_inflight"))
    router = HaikuRouter(client=fake)

    asyncio.run(router.classify("wait, keep the 10am", has_active_task=True))

    user_message = fake.calls[0]["messages"][0]["content"]
    assert "in-flight task" in user_message


def test_classify_raises_when_no_tool_call_present():
    fake = _FakeMessages(SimpleNamespace(content=[SimpleNamespace(type="text", text="uh")]))
    router = HaikuRouter(client=fake)

    with pytest.raises(RouterError):
        asyncio.run(router.classify("hello"))
