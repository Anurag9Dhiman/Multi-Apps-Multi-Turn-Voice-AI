"""Rolling per-hop latency aggregation for the "measure and log latency at
every hop from day one" deliverable (plan weeks 3-4).

Deliberately doesn't hand-time hops with our own timestamps: LiveKit Agents
already measures STT duration, end-of-utterance delay, and TTS
time-to-first-byte correctly (accounting for network/model internals we
can't see from outside). This module just aggregates whatever numbers the
framework hands us into p50/p95 per hop, which is the part that's actually
ours to build.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Samples:
    values: list[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        self.values.append(value)

    def percentile(self, p: float) -> float:
        s = sorted(self.values)
        k = (len(s) - 1) * p
        lo, hi = int(k), min(int(k) + 1, len(s) - 1)
        if lo == hi:
            return s[lo]
        return s[lo] + (s[hi] - s[lo]) * (k - lo)


class LatencyAggregator:
    """Keyed by hop name (e.g. "stt.duration", "tts.ttfb"); each `record`
    call adds one sample in seconds."""

    def __init__(self) -> None:
        self._hops: dict[str, _Samples] = {}

    def record(self, hop: str, seconds: float) -> None:
        self._hops.setdefault(hop, _Samples()).add(seconds)

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        return {
            hop: {
                "count": len(samples.values),
                "p50_ms": round(samples.percentile(0.5) * 1000, 1),
                "p95_ms": round(samples.percentile(0.95) * 1000, 1),
                "max_ms": round(max(samples.values) * 1000, 1),
            }
            for hop, samples in self._hops.items()
            if samples.values
        }

    def summary_line(self) -> str:
        snap = self.snapshot()
        if not snap:
            return "latency: no samples yet"
        parts = [
            f"{hop} p50={s['p50_ms']}ms p95={s['p95_ms']}ms n={s['count']}"
            for hop, s in sorted(snap.items())
        ]
        return "latency: " + " | ".join(parts)
