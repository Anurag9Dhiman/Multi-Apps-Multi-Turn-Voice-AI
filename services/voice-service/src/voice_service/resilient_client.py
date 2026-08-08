"""Reconnection resilience for CollectiveOSClient -- the gap flagged in
voice-service/README.md ("no reconnect-with-backoff yet") and designed as
a state machine in this project's own architecture blueprint:

    Pending -> Connecting -> Connected -> Reconnecting -> Connecting (retry)
                                        -> Failed (max_retries exhausted)
    Connected -> Idle (clean stop())

Wraps CollectiveOSClient rather than modifying it: the raw client stays a
thin, single-connection primitive (still used directly wherever a test
doesn't care about resilience, e.g. test_e2e_scenario_a.py); this layer
owns retry/backoff policy on top, and is the piece that actually closes
the gap -- it reuses the resume machinery Scenario B already proved works
(ConversationController.start(resume=True), the mock backend's user_id-keyed
Store), it just triggers that machinery automatically on an unexpected drop
instead of requiring a whole new call.

Deliberately does NOT retry `send()`. A write-risk_class action re-sent
after an ambiguous failure (did the server see it or not?) could duplicate
a real-world effect -- rescheduling a meeting twice, cancelling a
subscription twice. A dropped send raises; only the receive loop
reconnects transparently, since replaying reads is safe and replaying an
already-open task's *status* is exactly what resume is for.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable

import websockets
import websockets.exceptions
from voice_contract import AgentToVoiceEvent, VoiceToAgentEvent

from .collectiveos_client import CollectiveOSClient

logger = logging.getLogger("voice_service.resilient_client")

ClientState = str  # "pending" | "connecting" | "connected" | "reconnecting" | "failed" | "idle"

_RETRYABLE_ERRORS = (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException)


class ReconnectFailed(RuntimeError):
    """Raised once max_retries is exhausted -- ends the receive loop for
    good, same as a real, unrecoverable outage would."""


class ReconnectingCollectiveOSClient:
    def __init__(
        self,
        url: str,
        *,
        client_factory: Callable[[str], CollectiveOSClient] = CollectiveOSClient,
        max_retries: int = 6,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._url = url
        self._client_factory = client_factory
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

        self._client: CollectiveOSClient | None = None
        self._session_id: str | None = None
        self._user_id: str | None = None
        self._closing = False
        self.state: ClientState = "pending"

    async def connect(self, *, session_id: str, user_id: str, resume: bool = False) -> None:
        self._session_id = session_id
        self._user_id = user_id
        self._closing = False
        await self._connect_with_retry(resume=resume)

    async def _connect_with_retry(self, *, resume: bool) -> None:
        attempt = 0
        while True:
            self.state = "connecting"
            client = self._client_factory(self._url)
            try:
                await client.connect(session_id=self._session_id, user_id=self._user_id, resume=resume)
            except _RETRYABLE_ERRORS as exc:
                attempt += 1
                if attempt > self._max_retries:
                    self.state = "failed"
                    raise ReconnectFailed(f"gave up after {attempt - 1} retries") from exc
                delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
                self.state = "reconnecting"
                logger.warning(
                    "connect failed (attempt %d/%d), retrying in %.1fs: %r",
                    attempt, self._max_retries, delay, exc,
                )
                await asyncio.sleep(delay)
                continue
            self._client = client
            self.state = "connected"
            return

    async def send(self, event: VoiceToAgentEvent) -> None:
        if self._client is None:
            raise RuntimeError("not connected")
        await self._client.send(event)

    async def __aiter__(self) -> AsyncIterator[AgentToVoiceEvent]:
        while True:
            assert self._client is not None
            async for event in self._client:
                yield event
            # The inner iterator only ends via ConnectionClosed (converted
            # to StopAsyncIteration inside CollectiveOSClient.__anext__) --
            # that's indistinguishable from a clean close() by exception
            # type alone, which is exactly why _closing is tracked
            # explicitly rather than inferred from what was caught.
            if self._closing:
                return
            self.state = "reconnecting"
            logger.info("connection dropped unexpectedly, resuming session %s", self._session_id)
            try:
                await self._connect_with_retry(resume=True)
            except ReconnectFailed:
                return

    async def close(self) -> None:
        self._closing = True
        if self._client is not None:
            await self._client.close()
        self.state = "idle"
