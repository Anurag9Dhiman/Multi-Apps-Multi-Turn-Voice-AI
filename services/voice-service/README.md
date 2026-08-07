# voice-service

Weeks 3-6 of the MVP plan: LiveKit room, streaming STT (Deepgram), streaming
TTS (Cartesia), latency measured at every hop, a Haiku router, and a
CollectiveOS bridge over the frozen event contract (shared as the
[`voice-contract`](../../libs/voice-contract) package). Weeks 7-8 (speech
composer's full priority queue, Redis session/entity stack, multi-task
sessions, resume) aren't here yet.

## How a turn flows

1. LiveKit's STT/VAD produces a final transcript (`RoutingAgent.llm_node` in
   `agent.py` — deliberately yields nothing itself; see below).
2. `ConversationController.handle_utterance` (`conversation.py`) asks the
   Haiku router (`router.py`) for one of the six categories.
3. `small_talk`/`simple_lookup` → answered locally by `ack.py`, never
   crosses the wire.
4. Everything else → forwarded to CollectiveOS (`collectiveos_client.py`,
   points at `mock-agent-backend` by default) as `user_utterance` /
   `interrupt` / `confirmation_response` / `session_query`.
5. Whatever CollectiveOS sends back is spoken via the `speak` callback
   (`agent.py`), which honors contract priority — `high` interrupts
   whatever's currently playing, `low` is dropped if the user is mid-turn —
   and tracks utterances a barge-in cut off as undelivered (`turn_manager.py`,
   riding LiveKit's own `SpeechHandle.interrupted`, not a reimplementation).

`conversation.py` has no LiveKit import at all — it's the piece this phase
actually adds, and it's proven against a **real, live mock-agent-backend
over an actual socket** in `tests/test_e2e_scenario_a.py` (Haiku bypassed
via an explicit `router_class` argument, since there's no live Anthropic key
here — everything past routing runs unmocked).

## What's here vs. what needs live credentials to prove out

Unit- and integration-testable without any credentials (28 tests, all
green): the router's tool-call parsing, the ack templates, the full
`ConversationController` state machine, and — the real proof — Scenario A
end to end (new intent → confirmation → mid-confirmation edit → modified
confirmation → done) and Scenario C end to end (batch + mid-flight
interrupt + partial failure), both against a live `mock-agent-backend`
instance spun up in-process.

**Not verifiable in this environment** — no Deepgram/Cartesia/Anthropic/
LiveKit accounts exist here:
- That the router's actual classifications are correct in practice (its
  *plumbing* is tested; its *judgment* needs a real Anthropic key)
- That `session.say()`/`session.interrupt()` behave the way `agent.py`
  assumes under a real barge-in (LiveKit's interruption semantics, not
  ours — this is the one part of the LiveKit wiring most worth checking
  first once you can test live)
- Real-world audio and latency numbers

## Setup

```sh
cp .env.example .env   # DEEPGRAM_API_KEY, CARTESIA_API_KEY, ANTHROPIC_API_KEY
uv run pytest            # all unit + e2e tests, no live services required

# in one terminal: the mock backend this service talks to by default
cd ../mock-agent-backend && uv run mock-agent-backend

# in another: the voice service, console mode (no LiveKit account needed)
uv run voice-service console
```

`config.py` requires `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, and
`ANTHROPIC_API_KEY` (one combined error if any are missing).
`COLLECTIVEOS_WS_URL` defaults to `ws://localhost:8000/v1/ws` — mock-agent-backend's
own default port — override it once real CollectiveOS exists.
`LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` are only needed for
`voice-service dev`/`start` against a real room, not `console`. `--help`
works with zero env vars set.
