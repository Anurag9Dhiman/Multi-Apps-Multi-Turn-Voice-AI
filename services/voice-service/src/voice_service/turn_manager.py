"""Turn management: endpointing (when has the user finished speaking) and
barge-in (cut TTS fast, mark the interrupted utterance undelivered).

Both mechanisms are LiveKit Agents' own VAD/interruption handling
underneath -- AgentSession already cancels in-flight TTS the moment a
barge-in is detected. This module is the one place that pins our numbers
into that mechanism (plan: "cut TTS < 200ms") and tracks which spoken
utterances actually landed versus got cut off, via SpeechHandle.interrupted,
rather than re-implementing audio cancellation from scratch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class TurnManagerSettings:
    """Maps directly onto AgentSession/Agent kwargs of the same names."""

    # Endpointing bounds handed to LiveKit's own VAD/EOU turn detection.
    min_endpointing_delay: float = 0.4
    max_endpointing_delay: float = 6.0

    # Barge-in: anything under this is noise, not intent to interrupt.
    allow_interruptions: bool = True
    min_interruption_duration: float = 0.2

    def as_session_kwargs(self) -> dict[str, float | bool]:
        return {
            "min_endpointing_delay": self.min_endpointing_delay,
            "max_endpointing_delay": self.max_endpointing_delay,
            "allow_interruptions": self.allow_interruptions,
            "min_interruption_duration": self.min_interruption_duration,
        }


class _InterruptibleSpeech(Protocol):
    interrupted: bool

    def add_done_callback(self, callback: object) -> None: ...


@dataclass
class UndeliveredTracker:
    """Records utterances a barge-in cut off mid-speech, so the rest of the
    system can treat them as "the user didn't hear this" instead of
    silently assuming every spoken line landed."""

    _undelivered: list[str] = field(default_factory=list)

    def track(self, handle: _InterruptibleSpeech, text: str) -> None:
        def _on_done(h: _InterruptibleSpeech) -> None:
            if h.interrupted:
                self._undelivered.append(text)

        handle.add_done_callback(_on_done)

    def drain(self) -> list[str]:
        undelivered, self._undelivered = self._undelivered, []
        return undelivered
