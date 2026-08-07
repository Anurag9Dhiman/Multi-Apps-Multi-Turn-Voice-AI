"""Thin WebSocket client speaking the voice_to_agent / agent_to_voice
contract (see /contract at repo root). Talks to CollectiveOS in production
and to mock-agent-backend in dev/tests -- from this client's point of view
they're the same endpoint, which is the entire point of freezing the
contract in weeks 1-2.
"""

from __future__ import annotations

import json

import websockets
from voice_contract import (
    AgentToVoiceEvent,
    SessionEnd,
    SessionStart,
    VoiceToAgentEvent,
    dump_voice_event,
    parse_agent_to_voice,
)


class CollectiveOSClient:
    def __init__(self, url: str) -> None:
        self._url = url
        self._ws: websockets.ClientConnection | None = None
        self._session_id: str | None = None

    async def connect(self, *, session_id: str, user_id: str, resume: bool = False) -> None:
        self._ws = await websockets.connect(self._url)
        self._session_id = session_id
        await self.send(SessionStart(session_id=session_id, user_id=user_id, resume=resume))

    async def send(self, event: VoiceToAgentEvent) -> None:
        if self._ws is None:
            raise RuntimeError("not connected")
        await self._ws.send(json.dumps(dump_voice_event(event)))

    async def receive(self) -> AgentToVoiceEvent:
        if self._ws is None:
            raise RuntimeError("not connected")
        raw = await self._ws.recv()
        return parse_agent_to_voice(json.loads(raw))

    def __aiter__(self) -> CollectiveOSClient:
        return self

    async def __anext__(self) -> AgentToVoiceEvent:
        try:
            return await self.receive()
        except websockets.exceptions.ConnectionClosed:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        if self._ws is None:
            return
        if self._session_id is not None:
            try:
                await self.send(SessionEnd(session_id=self._session_id))
            except websockets.exceptions.ConnectionClosed:
                pass
        await self._ws.close()
        self._ws = None
