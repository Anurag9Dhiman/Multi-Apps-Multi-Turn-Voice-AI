"""Unit tests for the Gemini adapter's request/response translation, using
real google-genai types (constructed directly, no network) so the fixtures
can't drift from what the SDK actually returns. No live GEMINI_API_KEY is
used or needed -- `models=` is always a fake implementing just
`generate_content()`, matching the pattern used throughout this test suite
for every other provider-shaped dependency (router.py's MessagesClient,
CollectiveOSClient, etc.).
"""

import asyncio

from google.genai import types
from voice_service.gemini_client import GeminiMessagesClient
from voice_service.router import HaikuRouter
from voice_service.ack import AckGenerator


class FakeModels:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self.response


def _function_call_response(name: str, args: dict) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
                )
            )
        ]
    )


def _text_response(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]))]
    )


def test_tool_call_translates_to_anthropic_shaped_tool_use_block():
    async def scenario():
        fake = FakeModels(_function_call_response("classify_utterance", {"router_class": "new_intent"}))
        client = GeminiMessagesClient(models=fake, model="gemini-flash-latest")

        result = await client.create(
            model="claude-haiku-4-5-20251001",  # caller's own model string -- must be ignored
            max_tokens=64,
            system="classify",
            messages=[{"role": "user", "content": "clear my morning"}],
            tools=[
                {
                    "name": "classify_utterance",
                    "description": "x",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                }
            ],
            tool_choice={"type": "tool", "name": "classify_utterance"},
        )

        block = result.content[0]
        assert block.type == "tool_use"
        assert block.input == {"router_class": "new_intent"}
        # the adapter's own model wins, never the caller's Anthropic string
        assert fake.calls[0]["model"] == "gemini-flash-latest"

    asyncio.run(scenario())


def test_plain_text_response_translates_to_text_block():
    async def scenario():
        fake = FakeModels(_text_response("It's Tuesday."))
        client = GeminiMessagesClient(models=fake)

        result = await client.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            system="answer briefly",
            messages=[{"role": "user", "content": "what day is it"}],
        )

        block = result.content[0]
        assert block.type == "text"
        assert block.text == "It's Tuesday."

    asyncio.run(scenario())


def test_tool_choice_forces_the_named_function():
    async def scenario():
        fake = FakeModels(_function_call_response("classify_utterance", {"router_class": "session_query"}))
        client = GeminiMessagesClient(models=fake)

        await client.create(
            model="x",
            max_tokens=64,
            messages=[{"role": "user", "content": "where were we"}],
            tools=[{"name": "classify_utterance", "description": "", "input_schema": {"type": "object"}}],
            tool_choice={"type": "tool", "name": "classify_utterance"},
        )

        config = fake.calls[0]["config"]
        assert config.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.ANY
        assert config.tool_config.function_calling_config.allowed_function_names == ["classify_utterance"]

    asyncio.run(scenario())


def test_no_tools_means_no_tool_config_sent():
    async def scenario():
        fake = FakeModels(_text_response("hi"))
        client = GeminiMessagesClient(models=fake)

        await client.create(model="x", max_tokens=64, messages=[{"role": "user", "content": "hey"}])

        config = fake.calls[0]["config"]
        assert config.tools is None
        assert config.tool_config is None

    asyncio.run(scenario())


def test_haiku_router_works_unmodified_against_the_gemini_adapter():
    """The whole point of the adapter: router.py needs zero changes to
    work with either provider."""

    async def scenario():
        fake = FakeModels(_function_call_response("classify_utterance", {"router_class": "modify_inflight"}))
        router = HaikuRouter(client=GeminiMessagesClient(models=fake))

        result = await router.classify("wait, keep the 10am", has_active_task=True)

        assert result == "modify_inflight"

    asyncio.run(scenario())


def test_ack_generator_works_unmodified_against_the_gemini_adapter():
    async def scenario():
        fake = FakeModels(_text_response("Tuesday."))
        ack = AckGenerator(client=GeminiMessagesClient(models=fake))

        reply = await ack.instant_ack("simple_lookup", "what day is it")

        assert reply == "Tuesday."

    asyncio.run(scenario())
