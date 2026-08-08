# voice-service

Weeks 3-8 of the MVP plan: LiveKit room, streaming STT (Deepgram) / TTS
(Cartesia) with per-hop latency, a Haiku router with an instant-ack fast
path, a turn manager, and a CollectiveOS bridge over the frozen event
contract (shared as the [`voice-contract`](../../libs/voice-contract)
package) — now with multi-task session tracking, an entity stack, and
session persistence/resume on top.

## How a turn flows

1. LiveKit's STT/VAD produces a final transcript (`RoutingAgent.llm_node`
   in `agent.py` — yields nothing itself; see below).
2. `ConversationController.handle_utterance` (`conversation.py`) asks the
   Haiku router (`router.py`) for one of the six categories.
3. `small_talk`/`simple_lookup` → answered locally by `ack.py`, never
   crosses the wire.
4. Everything else → forwarded to CollectiveOS (`collectiveos_client.py`,
   points at `mock-agent-backend` by default) as `user_utterance` /
   `interrupt` / `confirmation_response` / `session_query`. `new_intent`
   utterances get pronouns resolved against `entity_stack.py` first
   (attached as `entity_refs`).
5. Whatever CollectiveOS sends back is spoken via `speech_composer.py`
   (priority preemption, one-breath logging) → `agent.py`'s `speak`
   binding, which tracks utterances a barge-in cut off as undelivered
   (`turn_manager.py`, riding LiveKit's own `SpeechHandle.interrupted`).
6. Task state (which tasks are active, which is waiting on the user) and
   the entity stack are snapshotted to a `SessionStore` (`session_store.py`
   — in-memory by default, Redis in production) keyed by user_id, so a
   session that resumes hours or days later picks up where it left off.

`conversation.py` and `speech_composer.py` have no LiveKit import at all —
they're what weeks 5-8 actually add, proven against a **real, live
mock-agent-backend over an actual socket**:
- `tests/test_e2e_scenario_a.py` — new intent → confirmation → mid-confirmation
  edit → modified confirmation → done
- `tests/test_e2e_scenario_b.py` — new intent → externally blocked → hang up
  → **new session, resumed** → status summary → done
- Scenario C's shape (batch + mid-flight interrupt + partial failure) also
  covered in `test_e2e_scenario_a.py`

Haiku is bypassed in all three via an explicit `router_class` argument
(no live Anthropic key in this environment) — everything else, including
the resume flow across two separate `ConversationController` instances
sharing one `SessionStore`, runs unmocked.

## What's here vs. what needs live credentials or infrastructure to prove out

Unit- and integration-tested (46 tests, all green): router tool-call
parsing, ack templates, the full multi-task `ConversationController` state
machine (including which task an unqualified follow-up targets when more
than one is active), the entity stack's pronoun resolution and its
deliberate refusal to treat sentence-initial capitalized words as entities,
session snapshot/restore, the speech composer's priority and one-breath
logic, the router eval harness's scoring/reporting (not the model's actual
judgment — see below), and all three reference scenarios end to end over a
real socket.

**Not verifiable in this environment:**
- The router's actual classification *judgment* in practice — its
  *plumbing* is tested; scoring it for real needs a live `ANTHROPIC_API_KEY`
  (`uv run python -m voice_service.router_eval`)
- `RedisSessionStore` — structurally complete, no Redis instance exists
  here to run it against
- That `session.say()`/`session.interrupt()` behave the way `agent.py`
  assumes under a real barge-in — LiveKit's interruption semantics, not
  ours; worth checking first once live testing is possible
- Real-world audio, latency numbers, and audio edge cases (noise, silence,
  crosstalk, dropped connections mid-call) — `CollectiveOSClient` degrades
  a dropped connection to a clean `StopAsyncIteration` rather than
  crashing, but there's no reconnect-with-backoff yet

**Out of reach from this repo entirely** (see
[`/collectiveos-integration`](../../collectiveos-integration) at the repo
root): the real CollectiveOS WebSocket endpoint and its DB migration live
in CollectiveOS's own repo, which doesn't exist in this workspace. That
directory is the prepared handoff — migration SQL plus a structural guide
— per the plan's own "open the integration branch early" sequencing.

## Setup

```sh
cp .env.example .env   # DEEPGRAM_API_KEY, CARTESIA_API_KEY, ANTHROPIC_API_KEY
uv run pytest            # all unit + e2e tests, no live services required

# in one terminal: the mock backend this service talks to by default
cd ../mock-agent-backend && uv run mock-agent-backend

# in another: the voice service, console mode (no LiveKit account needed)
uv run voice-service console

# score the router against the labeled eval set (needs a live Anthropic key)
uv run python -m voice_service.router_eval
```

`config.py` requires `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, and
`ANTHROPIC_API_KEY` (one combined error if any are missing).
`COLLECTIVEOS_WS_URL` defaults to `ws://localhost:8000/v1/ws` — mock-agent-backend's
own default port. `REDIS_URL` is optional; unset means session state is
in-process only (lost on restart) rather than persisted to Redis.
`LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` are only needed for
`voice-service dev`/`start` against a real room, not `console`. `--help`
works with zero env vars set.
