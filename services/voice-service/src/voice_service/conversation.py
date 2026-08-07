"""Framework-agnostic conversation orchestration: router decision in,
contract events out, CollectiveOS events back out as speech. No LiveKit
import here on purpose -- this is the piece weeks 5-6 actually adds, and
it's testable against a real mock-agent-backend over a real socket without
any audio hardware. agent.py is the thin LiveKit-specific binding on top.

Send and receive are decoupled deliberately: `handle_utterance` only
decides what to *send* based on the router's classification; a separate
receive loop speaks whatever CollectiveOS sends back, whenever it arrives.
That mirrors how the real duplex connection behaves -- an ack can arrive
while the user is still mid-sentence on their next utterance.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from voice_contract import (
    Ack,
    AgentToVoiceEvent,
    ClarificationRequest,
    ConfirmationRequest,
    ConfirmationResponse,
    Decision,
    Done,
    Error,
    Interrupt,
    Priority,
    Progress,
    SessionQuery,
    Speak as SpeakEvent,
    TaskUpdate,
    UserUtterance,
)

from .ack import AckGenerator
from .collectiveos_client import CollectiveOSClient
from .router import HaikuRouter

logger = logging.getLogger("voice_service.conversation")

Speak = Callable[[str, Priority], Awaitable[None]]

_APPROVE_WORDS = re.compile(r"\b(yes|yeah|yep|approve|go ahead|do it|sure|correct|confirm)\b", re.I)
# Deliberately narrow to unambiguous negations. Words like "cancel"/"stop"/
# "don't" are NOT included: "cancel the 9am" or "don't do the 11, just the
# 9" name a specific change, not a blanket no -- those need to reach
# CollectiveOS as a modification with the full text, not get silently
# downgraded to reject.
_REJECT_WORDS = re.compile(r"\b(no|nope|nah|negative|reject)\b", re.I)


def _parse_decision(text: str) -> tuple[Decision, str | None]:
    """Maps a spoken reply to a confirmation onto approve/reject/modify.
    Anything that isn't a clean yes/no is treated as a modification carrying
    the utterance itself -- CollectiveOS decides what to do with it."""
    if _APPROVE_WORDS.search(text) and not _REJECT_WORDS.search(text):
        return "approve", None
    if _REJECT_WORDS.search(text) and not _APPROVE_WORDS.search(text):
        return "reject", None
    return "modify", text


class ConversationController:
    def __init__(
        self,
        *,
        client: CollectiveOSClient,
        speak: Speak,
        router: HaikuRouter | None = None,
        ack: AckGenerator | None = None,
    ) -> None:
        self._client = client
        self._speak = speak
        self._router = router or HaikuRouter()
        self._ack = ack or AckGenerator()

        self._session_id: str | None = None
        self._user_id: str | None = None
        self._receive_task: asyncio.Task[None] | None = None

        self.current_task_id: str | None = None
        self.waiting_reason: str | None = None

    async def start(self, *, session_id: str, user_id: str, resume: bool = False) -> None:
        self._session_id = session_id
        self._user_id = user_id
        await self._client.connect(session_id=session_id, user_id=user_id, resume=resume)
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def stop(self) -> None:
        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except (asyncio.CancelledError, Exception):
                pass
        await self._client.close()

    async def handle_utterance(self, text: str, router_class: str | None = None) -> None:
        """router_class is normally decided by the Haiku router; tests may
        pass it directly to exercise the send-side logic without a live
        Anthropic key."""
        router_class = router_class or await self._router.classify(
            text, has_active_task=self.current_task_id is not None
        )

        if router_class in ("small_talk", "simple_lookup"):
            reply = await self._ack.instant_ack(router_class, text)
            await self._speak(reply, "low")
            return

        if router_class == "new_intent":
            await self._client.send(
                UserUtterance(
                    session_id=self._session_id,
                    text=text,
                    router_class="new_intent",
                    entity_refs={},
                    ts=datetime.now(UTC).isoformat(),
                )
            )
            return

        if router_class == "modify_inflight":
            if self.current_task_id is None:
                logger.warning("modify_inflight with no active task, dropping: %r", text)
                return
            await self._client.send(
                Interrupt(session_id=self._session_id, target_task_id=self.current_task_id, text=text)
            )
            return

        if router_class == "confirmation_reply":
            if self.current_task_id is None:
                logger.warning("confirmation_reply with no active task, dropping: %r", text)
                return
            decision, modification = _parse_decision(text)
            await self._client.send(
                ConfirmationResponse(
                    session_id=self._session_id,
                    task_id=self.current_task_id,
                    decision=decision,
                    modification=modification,
                )
            )
            return

        if router_class == "session_query":
            await self._client.send(SessionQuery(session_id=self._session_id, query=text))
            return

        logger.warning("unhandled router_class %r for utterance %r", router_class, text)

    async def _receive_loop(self) -> None:
        async for event in self._client:
            await self._handle_agent_event(event)

    async def _handle_agent_event(self, event: AgentToVoiceEvent) -> None:
        if isinstance(event, Ack):
            self.current_task_id = event.task_id
            await self._speak(event.text, "low")
        elif isinstance(event, (Progress, SpeakEvent)):
            self.current_task_id = event.task_id
            await self._speak(event.text, event.priority)
        elif isinstance(event, ConfirmationRequest):
            self.current_task_id = event.task_id
            self.waiting_reason = "user_confirm"
            await self._speak(event.speak, "high")
        elif isinstance(event, ClarificationRequest):
            self.current_task_id = event.task_id
            self.waiting_reason = "user_clarify"
            await self._speak(event.speak, "high")
        elif isinstance(event, TaskUpdate):
            self.current_task_id = event.task_id
            self.waiting_reason = event.waiting_reason
        elif isinstance(event, Done):
            await self._speak(event.summary_speak, "high")
            self.current_task_id = None
            self.waiting_reason = None
        elif isinstance(event, Error):
            await self._speak(event.speak, "high")
            if not event.recoverable:
                self.current_task_id = None
                self.waiting_reason = None
        else:
            logger.warning("unhandled agent event type %r", type(event).__name__)
