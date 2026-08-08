"""Automated eval harness for the router (plan sec. 9's "automated eval
suite for reasoning/routing quality", scoped here to routing since that's
what lives in this repo -- CollectiveOS's own reasoning quality is scored
in its own repo).

The labeled set is deliberately small (30 examples, ~5/class) to start --
plan sec. 5 calls for growing it to ~200 over time as real misroutes turn
up. Runnable two ways:

- `uv run python -m voice_service.router_eval` -- scores a real HaikuRouter,
  needs a live ANTHROPIC_API_KEY. Not runnable in this environment; see
  voice-service/README.md.
- tests/test_router_eval.py -- scores a fake, deterministic router to prove
  the scoring/reporting logic itself is correct. This is what's actually
  verified here: the harness, not the model's judgment.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from voice_contract import RouterClass

from .router import HaikuRouter

# (utterance, expected class, has_active_task context)
LABELED_UTTERANCES: tuple[tuple[str, RouterClass, bool], ...] = (
    # small_talk
    ("hey there", "small_talk", False),
    ("thanks so much", "small_talk", False),
    ("how's it going", "small_talk", False),
    ("good morning", "small_talk", False),
    ("talk to you later", "small_talk", False),
    # simple_lookup
    ("what did you just say", "simple_lookup", True),
    ("what time is my next meeting", "simple_lookup", False),
    ("who am I meeting with at 3", "simple_lookup", False),
    ("can you repeat that", "simple_lookup", True),
    ("what's on my calendar tomorrow", "simple_lookup", False),
    # new_intent
    ("clear my morning, I'm sick", "new_intent", False),
    ("cancel the subscriptions I'm not using", "new_intent", False),
    ("help me prep for the board meeting Friday", "new_intent", False),
    ("book a flight to Denver next week", "new_intent", False),
    ("send Priya the updated deck", "new_intent", False),
    # modify_inflight
    ("wait, keep the 10am", "modify_inflight", True),
    ("actually make it 3pm instead", "modify_inflight", True),
    ("hold on, don't cancel Spotify", "modify_inflight", True),
    ("change that to next Tuesday", "modify_inflight", True),
    ("scratch that, use the other deck", "modify_inflight", True),
    # confirmation_reply
    ("yes, go ahead", "confirmation_reply", True),
    ("no, don't do that", "confirmation_reply", True),
    ("sure, that works", "confirmation_reply", True),
    ("approve it", "confirmation_reply", True),
    ("that's correct", "confirmation_reply", True),
    # session_query
    ("where were we", "session_query", True),
    ("what's the status on that", "session_query", True),
    ("did that finish", "session_query", True),
    ("is the board prep done yet", "session_query", True),
    ("what have you been working on", "session_query", True),
)


@dataclass
class EvalResult:
    total: int
    correct: int
    misclassifications: list[tuple[str, RouterClass, RouterClass]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def report(self) -> str:
        lines = [f"accuracy: {self.correct}/{self.total} ({self.accuracy:.1%})"]
        for text, expected, actual in self.misclassifications:
            lines.append(f"  MISS  {text!r} -- expected {expected}, got {actual}")
        return "\n".join(lines)


async def run_eval(
    classify,
    dataset: tuple[tuple[str, RouterClass, bool], ...] = LABELED_UTTERANCES,
) -> EvalResult:
    """`classify` is anything shaped like HaikuRouter.classify (or a fake
    with the same signature) -- kept as a plain callable, not a HaikuRouter
    type hint, so tests can inject a deterministic fake."""
    correct = 0
    misses: list[tuple[str, RouterClass, RouterClass]] = []
    for text, expected, has_active_task in dataset:
        actual = await classify(text, has_active_task=has_active_task)
        if actual == expected:
            correct += 1
        else:
            misses.append((text, expected, actual))
    return EvalResult(total=len(dataset), correct=correct, misclassifications=misses)


async def _main() -> None:
    router = HaikuRouter()
    result = await run_eval(router.classify)
    print(result.report())


if __name__ == "__main__":
    asyncio.run(_main())
