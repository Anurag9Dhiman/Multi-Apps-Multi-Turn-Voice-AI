# mock-agent-backend

Scripted stand-in for CollectiveOS, implementing the [event contract](../../contract/README.md)
so the voice layer can be built and tested end to end before real
integration. Exposes one endpoint: `ws://<host>/v1/ws`.

Scripted scenarios (matched by keyword on the first `new_intent` utterance
of a session — see `src/mock_agent_backend/scenarios.py`):

| trigger phrase | scenario |
|---|---|
| "clear my morning" | A — follow-up message mid-confirmation |
| "board meeting" / "board prep" | B — multi-day plan, blocks externally, resumes next session |
| "cancel" + "subscription" | C — batch action, mid-flight interrupt, partial failure |

## Run it

```sh
uv run mock-agent-backend        # serves on :8000
uv run pytest                    # event-trace tests replay contract/scenarios/*.json
```

`MOCK_AGENT_STEP_DELAY_S` (default `0.02`) paces scripted events for a more
realistic manual demo; `MOCK_AGENT_INTERRUPT_WINDOW_S` (default `0.3`) is
how long scenario C holds a batch open for a mid-flight interrupt before
committing to running it uninterrupted. `SENTRY_DSN` (optional) enables
error tracking; unset means no tracking, not a startup failure.

State is in-memory and keyed by `user_id`, matching the plan's MVP scope —
no database, single process, good for the automated tests and local demos
only.
