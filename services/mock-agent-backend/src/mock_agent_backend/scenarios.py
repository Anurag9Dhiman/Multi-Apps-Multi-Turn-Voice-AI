"""Scripted behaviors for the three reference scenarios in
../../../../contract/scenarios/*.json. Each function drives one task from
`new_intent` (or, for scenario B's resume half, from `session_query`) to a
terminal event, sending events through `sender` and reading the next
voice-layer event through `incoming` where the script needs to branch on
what the user said.

This is deliberately imperative rather than a generic scenario DSL: three
scripts, each read top to bottom, is easier to audit against the plan's
prose than a data-driven interpreter would be for so few cases.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

from . import contract as c

# Overridable so a manually-run demo server can feel real (e.g. 0.6) while
# the test suite stays fast.
STEP_DELAY_SECONDS = float(os.environ.get("MOCK_AGENT_STEP_DELAY_S", "0.02"))

# How long to hold the batch open for a mid-flight interrupt before
# committing to "no interrupt arrived". Must be an actual await, not a
# get_nowait() check -- the client's interrupt is a genuine network
# round-trip away and will not have reached the queue yet if we don't wait.
INTERRUPT_WINDOW_SECONDS = float(os.environ.get("MOCK_AGENT_INTERRUPT_WINDOW_S", "0.3"))

Sender = Callable[[c.AgentToVoiceEvent], Awaitable[None]]


async def _beat() -> None:
    if STEP_DELAY_SECONDS:
        await asyncio.sleep(STEP_DELAY_SECONDS)


def matches_scenario_a(text: str) -> bool:
    return "clear my morning" in text.lower()


def matches_scenario_b(text: str) -> bool:
    t = text.lower()
    return "board meeting" in t or "board prep" in t


def matches_scenario_c(text: str) -> bool:
    t = text.lower()
    return "cancel" in t and "subscription" in t


def _join_and(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


async def run_scenario_a(
    task_id: str, send: Sender, incoming: asyncio.Queue[c.VoiceToAgentEvent]
) -> None:
    """New intent -> confirmation -> user follow-up message mid-confirmation
    modifies the pending action -> modified confirmation -> completion."""
    await send(c.Ack(task_id=task_id, text="Checking your calendar now."))
    await _beat()
    await send(
        c.Progress(task_id=task_id, text="Found three meetings this morning.")
    )
    await send(c.TaskUpdate(task_id=task_id, status="planning", waiting_reason=None))
    await _beat()

    keep_10am = False
    speak = "I can move the 9, 10, and 11 o'clock to Thursday. Shall I go ahead?"
    while True:
        await send(
            c.ConfirmationRequest(
                task_id=task_id,
                speak=speak,
                options=["approve", "reject", "modify"],
                risk_class="write",
            )
        )
        await send(
            c.TaskUpdate(task_id=task_id, status="waiting", waiting_reason="user_confirm")
        )

        event = await incoming.get()
        if isinstance(event, c.Interrupt) and "keep the 10am" in event.text.lower():
            keep_10am = True
            speak = "Got it - I'll move the 9 and 11, and keep the 10am. Shall I go ahead?"
            continue
        if isinstance(event, c.ConfirmationResponse) and event.decision == "approve":
            break

    await send(
        c.TaskUpdate(
            task_id=task_id,
            status="running",
            waiting_reason=None,
            step=c.TaskStep(tool="calendar.reschedule", risk_class="write"),
        )
    )
    await _beat()
    moved = "the 9 o'clock and the 11 o'clock" if keep_10am else "all three meetings"
    await send(c.Progress(task_id=task_id, text=f"Moved {moved} to Thursday."))
    await send(c.TaskUpdate(task_id=task_id, status="completed", waiting_reason=None))
    stays = ", the 10am stays" if keep_10am else ""
    await send(
        c.Done(
            task_id=task_id,
            outcome="completed",
            summary_speak=f"Done - two meetings moved to Thursday{stays}.",
        )
    )


async def run_scenario_b_start(task_id: str, send: Sender) -> None:
    """First half: opens the task, then gets externally blocked (waiting on
    a document owner to share access) and stays blocked when the call ends."""
    await send(c.Ack(task_id=task_id, text="On it - pulling together what you'll need for Friday."))
    await send(c.TaskUpdate(task_id=task_id, status="planning", waiting_reason=None))
    await _beat()
    await send(
        c.Progress(task_id=task_id, text="Found last quarter's board deck and your prep notes.")
    )
    await send(
        c.TaskUpdate(
            task_id=task_id,
            status="running",
            waiting_reason=None,
            step=c.TaskStep(tool="docs.search", risk_class="read"),
        )
    )
    await _beat()
    await send(
        c.Speak(
            task_id=task_id,
            text="I've asked Priya to share edit access to the deck - I'll keep going once she does.",
        )
    )
    await send(c.TaskUpdate(task_id=task_id, status="blocked", waiting_reason="external"))


async def run_scenario_b_resume(task_id: str, send: Sender) -> None:
    """Second half: a session_query on the resumed connection gets a status
    summary, then the task finishes."""
    await send(
        c.Speak(
            task_id=task_id,
            text=(
                "Yesterday I started your board prep and was waiting on Priya to "
                "share deck access - that came through overnight, so I finished "
                "the metrics slide."
            ),
        )
    )
    await _beat()
    await send(
        c.TaskUpdate(
            task_id=task_id,
            status="running",
            waiting_reason=None,
            step=c.TaskStep(tool="docs.draft_slide", risk_class="read"),
        )
    )
    await send(c.TaskUpdate(task_id=task_id, status="completed", waiting_reason=None))
    await send(
        c.Done(
            task_id=task_id,
            outcome="completed",
            summary_speak="Board prep is done - the updated metrics slide is in the deck, ready for Friday.",
        )
    )


async def run_scenario_c(
    task_id: str, send: Sender, incoming: asyncio.Queue[c.VoiceToAgentEvent]
) -> None:
    """New intent opens a batch action -> confirmation -> approved ->
    mid-flight interrupt drops one item -> remaining items run, one fails ->
    done with outcome partial."""
    await send(c.Ack(task_id=task_id, text="Let me check what you're subscribed to."))
    await send(c.TaskUpdate(task_id=task_id, status="planning", waiting_reason=None))
    await _beat()
    items = ["Spotify", "Acme Gym", "ClipCloud", "NewsDaily"]
    await send(
        c.Progress(
            task_id=task_id,
            text=(
                "Found four subscriptions you haven't used in over two months: "
                + _join_and(items)
                + "."
            ),
        )
    )
    await send(
        c.ConfirmationRequest(
            task_id=task_id,
            speak="Want me to cancel all four?",
            options=["approve", "reject", "modify"],
            risk_class="write",
        )
    )
    await send(c.TaskUpdate(task_id=task_id, status="waiting", waiting_reason="user_confirm"))

    event = await incoming.get()
    while not (isinstance(event, c.ConfirmationResponse) and event.decision == "approve"):
        event = await incoming.get()

    await send(
        c.TaskUpdate(
            task_id=task_id,
            status="running",
            waiting_reason=None,
            step=c.TaskStep(tool="billing.cancel", risk_class="write"),
        )
    )

    keep = set()
    try:
        interrupt = await asyncio.wait_for(incoming.get(), timeout=INTERRUPT_WINDOW_SECONDS)
    except asyncio.TimeoutError:
        interrupt = None
    if isinstance(interrupt, c.Interrupt):
        for item in items:
            if item.lower() in interrupt.text.lower():
                keep.add(item)
        kept = ", ".join(sorted(keep)) or "nothing"
        await send(c.Speak(task_id=task_id, text=f"Got it, keeping {kept} - cancelling the other three."))

    fails = {"ClipCloud"}
    cancelled: list[str] = []
    failed: list[str] = []
    for item in items:
        if item in keep:
            continue
        await send(
            c.TaskUpdate(
                task_id=task_id,
                status="running",
                waiting_reason=None,
                step=c.TaskStep(tool="billing.cancel", risk_class="write"),
            )
        )
        await _beat()
        if item in fails:
            failed.append(item)
            await send(
                c.Progress(
                    task_id=task_id,
                    text=f"{item}'s cancellation page is down - couldn't complete that one.",
                )
            )
        else:
            cancelled.append(item)
            await send(c.Progress(task_id=task_id, text=f"{item} cancelled."))

    await send(c.TaskUpdate(task_id=task_id, status="completed", waiting_reason=None))
    outcome = "partial" if failed else "completed"
    kept_clause = f", kept {', '.join(sorted(keep))} like you asked" if keep else ""
    failed_clause = (
        f". {', '.join(failed)}'s site was down, so that one's still active - I'll retry later."
        if failed
        else "."
    )
    await send(
        c.Done(
            task_id=task_id,
            outcome=outcome,
            summary_speak=f"Done - cancelled {_join_and(cancelled)}{kept_clause}{failed_clause}",
        )
    )
