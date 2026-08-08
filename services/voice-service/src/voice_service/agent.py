"""LiveKit Agents entrypoint. Weeks 3-4 proved the raw STT/TTS round trip
(EchoAgent, now retired); weeks 5-6 add the turn manager, the Haiku router,
and the CollectiveOS bridge on top of it.

This module is deliberately thin: routing decisions, contract event
forwarding, and confirmation/interrupt handling all live in conversation.py
(framework-agnostic, unit-tested against a real mock-agent-backend socket).
RoutingAgent's only job is to hand LiveKit's final transcripts to the
controller and let the controller's `speak` callback drive session.say() --
with priority preemption and undelivered-utterance tracking wired to
LiveKit's own interruption mechanism rather than reimplementing it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable

from anthropic import AsyncAnthropic
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    MetricsCollectedEvent,
    WorkerOptions,
    cli,
    metrics,
)
from livekit.agents.llm import ChatContext
from livekit.plugins import cartesia, deepgram, silero

from .ack import AckGenerator
from .config import Settings
from .conversation import ConversationController
from .entity_stack import EntityStack
from .latency import LatencyAggregator
from .resilient_client import ReconnectingCollectiveOSClient
from .router import HaikuRouter
from .session_store import InMemorySessionStore, RedisSessionStore
from .speech_composer import SpeechComposer
from .turn_manager import TurnManagerSettings, UndeliveredTracker

logger = logging.getLogger("voice_service.agent")

TURN_MANAGER_SETTINGS = TurnManagerSettings()


class RoutingAgent(Agent):
    """No LLM configured. llm_node hands the final transcript to the
    ConversationController and yields nothing -- the controller speaks
    everything (instant acks, forwarded CollectiveOS events) out of band
    via the `speak` callback, not through the turn-based reply pipeline."""

    def __init__(self, controller: ConversationController) -> None:
        super().__init__(instructions="Route utterances; never reply directly.")
        self._controller = controller

    async def llm_node(
        self, chat_ctx: ChatContext, tools, model_settings
    ) -> AsyncIterable[str]:
        last_user = next(
            (m for m in reversed(chat_ctx.messages()) if m.role == "user"),
            None,
        )
        text = last_user.text_content if last_user else ""
        if text:
            await self._controller.handle_utterance(text)
        return
        yield  # pragma: no cover -- makes this an async generator


def _record_metric(aggregator: LatencyAggregator, metric: object) -> None:
    if isinstance(metric, metrics.STTMetrics):
        aggregator.record("stt.duration", metric.duration)
    elif isinstance(metric, metrics.EOUMetrics):
        aggregator.record("eou.end_of_utterance_delay", metric.end_of_utterance_delay)
    elif isinstance(metric, metrics.TTSMetrics):
        aggregator.record("tts.ttfb", metric.ttfb)


def _make_speech_composer(session: AgentSession, tracker: UndeliveredTracker) -> SpeechComposer:
    async def raw_speak(text: str) -> object:
        handle = session.say(text)
        tracker.track(handle, text)
        return handle

    async def raw_interrupt() -> None:
        await session.interrupt()

    return SpeechComposer(
        raw_speak=raw_speak,
        raw_interrupt=raw_interrupt,
        is_user_speaking=lambda: session.user_state == "speaking",
    )


async def entrypoint(ctx: JobContext) -> None:
    settings = Settings()
    aggregator = LatencyAggregator()
    tracker = UndeliveredTracker()

    session = AgentSession(
        stt=deepgram.STT(api_key=settings.deepgram_api_key),
        tts=cartesia.TTS(api_key=settings.cartesia_api_key),
        vad=silero.VAD.load(),
        **TURN_MANAGER_SETTINGS.as_session_kwargs(),
    )

    anthropic_messages = AsyncAnthropic(api_key=settings.anthropic_api_key).messages
    composer = _make_speech_composer(session, tracker)

    if settings.redis_url:
        session_store = RedisSessionStore.from_url(settings.redis_url)
    else:
        session_store = InMemorySessionStore()

    controller = ConversationController(
        client=ReconnectingCollectiveOSClient(settings.collectiveos_ws_url),
        speak=composer.speak,
        router=HaikuRouter(client=anthropic_messages),
        ack=AckGenerator(client=anthropic_messages),
        entities=EntityStack(),
        session_store=session_store,
    )

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent) -> None:
        metrics.log_metrics(ev.metrics)
        _record_metric(aggregator, ev.metrics)
        logger.info(aggregator.summary_line())

    await ctx.connect()
    # resume=False: real resume-detection needs a signal from the call setup
    # (room metadata / participant attributes carrying "this user has a
    # pending task") that doesn't exist yet -- that's an integration-time
    # decision for whatever places the call, not something inferable here.
    await controller.start(session_id=ctx.room.name, user_id=ctx.job.id, resume=False)

    async def _stop_controller() -> None:
        await controller.stop()

    ctx.add_shutdown_callback(_stop_controller)

    await session.start(agent=RoutingAgent(controller), room=ctx.room)


def main() -> None:
    # ws_url/api_key/api_secret are left unset here: WorkerOptions already
    # falls back to the LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET env
    # vars itself, and only needs them once a job actually connects -- not
    # at CLI parse time, which is what eagerly building Settings() here
    # would otherwise block (e.g. `voice-service --help`).
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))


if __name__ == "__main__":
    main()
