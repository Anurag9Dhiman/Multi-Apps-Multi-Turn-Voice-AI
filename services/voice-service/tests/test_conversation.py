import asyncio

import pytest
from voice_contract import Ack, ConfirmationRequest, Done, Interrupt, SessionQuery, UserUtterance
from voice_service.conversation import ConversationController


class FakeClient:
    """Stands in for CollectiveOSClient: records what's sent, and lets a
    test push agent_to_voice events for the controller's receive loop to
    consume, without touching a real socket."""

    def __init__(self) -> None:
        self.sent: list[object] = []
        self.connected = False
        self.closed = False
        self._queue: asyncio.Queue = asyncio.Queue()

    async def connect(self, *, session_id, user_id, resume=False):
        self.connected = True
        self.session_id = session_id

    async def send(self, event):
        self.sent.append(event)

    def push(self, event) -> None:
        self._queue.put_nowait(event)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._queue.get()

    async def close(self):
        self.closed = True


class FakeRouter:
    def __init__(self, router_class: str) -> None:
        self.router_class = router_class

    async def classify(self, text, *, has_active_task=False):
        return self.router_class


class FakeAck:
    async def instant_ack(self, router_class, text):
        return f"ack:{router_class}"


async def _settle() -> None:
    """Let the controller's background receive-loop task process whatever
    was just pushed onto the fake client's queue."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def _controller(client: FakeClient, router_class: str | None = None):
    speak_calls: list[tuple[str, str]] = []

    async def speak(text, priority):
        speak_calls.append((text, priority))

    controller = ConversationController(
        client=client,
        speak=speak,
        router=FakeRouter(router_class) if router_class else None,
        ack=FakeAck(),
    )
    return controller, speak_calls


def test_small_talk_speaks_locally_without_sending_anything():
    async def scenario():
        client = FakeClient()
        controller, speak_calls = _controller(client, "small_talk")
        await controller.start(session_id="s1", user_id="u1")

        await controller.handle_utterance("hey")

        assert speak_calls == [("ack:small_talk", "low")]
        assert client.sent == []
        await controller.stop()

    asyncio.run(scenario())


def test_new_intent_forwards_as_user_utterance():
    async def scenario():
        client = FakeClient()
        controller, _ = _controller(client, "new_intent")
        await controller.start(session_id="s1", user_id="u1")

        await controller.handle_utterance("clear my morning, I'm sick")

        assert len(client.sent) == 1
        sent = client.sent[0]
        assert isinstance(sent, UserUtterance)
        assert sent.session_id == "s1"
        assert sent.router_class == "new_intent"
        assert sent.text == "clear my morning, I'm sick"
        await controller.stop()

    asyncio.run(scenario())


def test_ack_event_sets_current_task_and_speaks_it():
    async def scenario():
        client = FakeClient()
        controller, speak_calls = _controller(client)
        await controller.start(session_id="s1", user_id="u1")

        client.push(Ack(task_id="t1", text="Checking your calendar now."))
        await _settle()

        assert controller.current_task_id == "t1"
        assert speak_calls == [("Checking your calendar now.", "low")]
        await controller.stop()

    asyncio.run(scenario())


def test_modify_inflight_sends_interrupt_targeting_current_task():
    async def scenario():
        client = FakeClient()
        controller, _ = _controller(client, "modify_inflight")
        await controller.start(session_id="s1", user_id="u1")
        client.push(Ack(task_id="t1", text="Checking your calendar now."))
        await _settle()

        await controller.handle_utterance("wait, keep the 10am")

        interrupt = client.sent[-1]
        assert isinstance(interrupt, Interrupt)
        assert interrupt.target_task_id == "t1"
        assert interrupt.text == "wait, keep the 10am"
        await controller.stop()

    asyncio.run(scenario())


def test_modify_inflight_with_no_active_task_is_dropped_not_crashed():
    async def scenario():
        client = FakeClient()
        controller, _ = _controller(client, "modify_inflight")
        await controller.start(session_id="s1", user_id="u1")

        await controller.handle_utterance("wait, keep the 10am")  # no active task yet

        assert client.sent == []
        await controller.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "text,expected_decision,expected_modification",
    [
        ("yes, go ahead", "approve", None),
        ("no, don't do that", "reject", None),
        ("actually just cancel the 9am", "modify", "actually just cancel the 9am"),
    ],
)
def test_confirmation_reply_maps_to_decision(text, expected_decision, expected_modification):
    async def scenario():
        client = FakeClient()
        controller, _ = _controller(client, "confirmation_reply")
        await controller.start(session_id="s1", user_id="u1")
        client.push(ConfirmationRequest(task_id="t1", speak="Shall I go ahead?", options=["approve", "reject", "modify"], risk_class="write"))
        await _settle()

        await controller.handle_utterance(text)

        response = client.sent[-1]
        assert response.task_id == "t1"
        assert response.decision == expected_decision
        assert response.modification == expected_modification
        await controller.stop()

    asyncio.run(scenario())


def test_session_query_forwards_the_query():
    async def scenario():
        client = FakeClient()
        controller, _ = _controller(client, "session_query")
        await controller.start(session_id="s1", user_id="u1")

        await controller.handle_utterance("where were we")

        sent = client.sent[-1]
        assert isinstance(sent, SessionQuery)
        assert sent.query == "where were we"
        await controller.stop()

    asyncio.run(scenario())


def test_done_clears_active_task_and_speaks_summary_at_high_priority():
    async def scenario():
        client = FakeClient()
        controller, speak_calls = _controller(client)
        await controller.start(session_id="s1", user_id="u1")
        client.push(Ack(task_id="t1", text="Checking your calendar now."))
        await _settle()

        client.push(Done(task_id="t1", outcome="completed", summary_speak="All done."))
        await _settle()

        assert controller.current_task_id is None
        assert ("All done.", "high") in speak_calls
        await controller.stop()

    asyncio.run(scenario())
