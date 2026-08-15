# voice-service

Weeks 3-10 of the MVP plan: LiveKit room, streaming STT (Deepgram) / TTS
(Cartesia) with per-hop latency, an LLM router with an instant-ack fast
path, a turn manager, and a CollectiveOS bridge over the frozen event
contract (shared as the [`voice-contract`](../../libs/voice-contract)
package) — with multi-task session tracking, an entity stack, session
persistence/resume, and reconnection resilience on top.

The router and ack generator run on **either Anthropic (Claude Haiku,
designed default) or Gemini** — `gemini_client.py` adapts Gemini's
function-calling API to the exact client shape `router.py`/`ack.py` already
expect from Anthropic, so neither module (or their tests) knows or cares
which provider is actually behind them. Only `ANTHROPIC_API_KEY` or
`GEMINI_API_KEY` needs to exist, not both — see `config.py`'s
`resolved_llm_provider`.

## How a turn flows

1. LiveKit's STT/VAD produces a final transcript (`RoutingAgent.llm_node`
   in `agent.py` — yields nothing itself; see below).
2. `ConversationController.handle_utterance` (`conversation.py`) asks the
   router (`router.py`, whichever provider `llm_provider.py` resolved) for
   one of the six categories.
3. `small_talk`/`simple_lookup` → answered locally by `ack.py`, never
   crosses the wire.
4. Everything else → forwarded to CollectiveOS over
   `ReconnectingCollectiveOSClient` (`resilient_client.py`, wraps the raw
   `collectiveos_client.py`; points at `mock-agent-backend` by default) as
   `user_utterance` / `interrupt` / `confirmation_response` /
   `session_query`. `new_intent` utterances get pronouns resolved against
   `entity_stack.py` first (attached as `entity_refs`). An unexpected drop
   is retried with exponential backoff and resumes the same session
   automatically — `handle_utterance`'s send side and `_receive_loop`'s
   receive side don't need to know a reconnect happened.
5. Whatever CollectiveOS sends back is spoken via `speech_composer.py`
   (priority preemption, one-breath logging) → `agent.py`'s `speak`
   binding, which tracks utterances a barge-in cut off as undelivered
   (`turn_manager.py`, riding LiveKit's own `SpeechHandle.interrupted`).
6. Task state (which tasks are active, which is waiting on the user) and
   the entity stack are snapshotted to a `SessionStore` (`session_store.py`
   — in-memory by default, Redis in production) keyed by user_id, so a
   session that resumes hours or days later picks up where it left off.

Every call into `handle_utterance` is metered first, before the router or
CollectiveOS ever sees it: `rate_limiter.py`'s per-user token bucket
(`InMemoryRateLimiter` by default, `RedisRateLimiter` in production) caps
bursts and degrades a flood to "let's slow down a moment" instead of an
unbounded Anthropic bill or a runaway loop.

`conversation.py` and `speech_composer.py` have no LiveKit import at all —
they're what weeks 5-8 actually add, proven against a **real, live
mock-agent-backend over an actual socket**:
- `tests/test_e2e_scenario_a.py` — new intent → confirmation → mid-confirmation
  edit → modified confirmation → done
- `tests/test_e2e_scenario_b.py` — new intent → externally blocked → hang up
  → **new session, resumed** → status summary → done
- Scenario C's shape (batch + mid-flight interrupt + partial failure) also
  covered in `test_e2e_scenario_a.py`
- `tests/test_e2e_reconnect.py` — the underlying socket is force-closed
  mid-task (bypassing our own `close()`, so it's indistinguishable from a
  real network drop), and the **same** `ConversationController` — not a
  freshly constructed one — reconnects with backoff, resumes, and finishes
  the task

The router is bypassed in all three via an explicit `router_class` argument
(no live LLM key of either kind in this environment) — everything else,
including the resume flow across two separate `ConversationController`
instances sharing one `SessionStore`, runs unmocked.

## What's here vs. what needs live credentials or infrastructure to prove out

Unit- and integration-tested (73 tests, all green): router tool-call
parsing, ack templates, the full multi-task `ConversationController` state
machine (including which task an unqualified follow-up targets when more
than one is active), the entity stack's pronoun resolution and its
deliberate refusal to treat sentence-initial capitalized words as entities,
session snapshot/restore, the speech composer's priority and one-breath
logic, the router eval harness's scoring/reporting (not the model's actual
judgment — see below), the reconnect wrapper's backoff/give-up logic against
a fake transport, the rate limiter's token-bucket math, the Gemini
adapter's request/response translation against real `google-genai` types
(constructed directly, no network) *and* that `HaikuRouter`/`AckGenerator`
work against it completely unmodified, and all three reference scenarios
*plus* an unexpected mid-task connection drop, end to end over a real
socket.

**Not verifiable in this environment:**
- The router's actual classification *judgment* in practice, on either
  provider — its *plumbing* is tested for both; scoring it for real needs
  a live `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`
  (`uv run python -m voice_service.router_eval`)
- `RedisSessionStore` / `RedisRateLimiter` — structurally complete, no
  Redis instance exists here to run either against
- That `session.say()`/`session.interrupt()` behave the way `agent.py`
  assumes under a real barge-in — LiveKit's interruption semantics, not
  ours; worth checking first once live testing is possible
- That Sentry actually receives an event — `SENTRY_DSN` unset here means
  `sentry_sdk.init()` is never called at all; the wiring is one `if` away
  from live, not tested end to end
- Real-world audio, latency numbers, and audio edge cases (noise, silence,
  crosstalk) — genuinely need hardware this environment doesn't have.
  Dropped-connection recovery specifically *is* now covered (see above) —
  that gap is closed, not just narrowed.

**Out of reach from this repo entirely** (see
[`/collectiveos-integration`](../../collectiveos-integration) at the repo
root): the real CollectiveOS WebSocket endpoint and its DB migration live
in CollectiveOS's own repo, which doesn't exist in this workspace. That
directory is the prepared handoff — migration SQL plus a structural guide
— per the plan's own "open the integration branch early" sequencing.

## Setup

```sh
cp .env.example .env   # DEEPGRAM_API_KEY, CARTESIA_API_KEY, + one of ANTHROPIC_API_KEY/GEMINI_API_KEY
uv run pytest            # all unit + e2e tests, no live services required

# in one terminal: the mock backend this service talks to by default
cd ../mock-agent-backend && uv run mock-agent-backend

# in another: the voice service, console mode (no LiveKit account needed)
uv run voice-service console

# score the router against the labeled eval set (needs a live LLM key)
uv run python -m voice_service.router_eval
```

`config.py` requires `DEEPGRAM_API_KEY` and `CARTESIA_API_KEY` unconditionally,
plus **at least one** of `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` (one combined
error either way if something's missing). If both LLM keys are set, Anthropic
wins unless `LLM_PROVIDER=gemini` says otherwise — `resolved_llm_provider`
is the single source of truth every call site defers to. `GEMINI_MODEL`
defaults to `gemini-flash-latest`, overridable. `COLLECTIVEOS_WS_URL`
defaults to `ws://localhost:8000/v1/ws` — mock-agent-backend's own default
port. `REDIS_URL` is optional; unset means session state and rate-limit
counters are in-process only (lost on restart) rather than persisted to
Redis. `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` are only needed
for `voice-service dev`/`start` against a real room, not `console`.
`SENTRY_DSN` is optional and read directly in `main()`, not through
`Settings()` — same reasoning as `LIVEKIT_URL`: `--help` works with zero
env vars set, and that has to keep being true as things get added, not
just be true today.

**A version pin worth knowing about:** `google-genai` (every published
version) requires `websockets<17.0`, which conflicted with the
`websockets>=17.0.1` this project had pinned for `resilient_client.py`.
Resolved by relaxing to `websockets>=14.0,<17.0` — the `websockets.asyncio`
module structure both `collectiveos_client.py` and `resilient_client.py`
depend on has existed since 13.0, well within that range. Full suite
re-verified green at `websockets==16.1.1` before this was considered safe,
not assumed.
