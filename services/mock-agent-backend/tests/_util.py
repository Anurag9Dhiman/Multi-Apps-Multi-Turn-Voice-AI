"""Shared helpers for replaying contract/scenarios/*.json traces against the
mock backend over a real (in-process) WebSocket connection.

Fields the mock backend mints itself at runtime (task_id) won't match the
fixture's placeholder value, so comparisons strip id fields rather than
diffing them literally; session_id/user_id are voice-layer-chosen and are
sent verbatim from the fixture, so they round-trip correctly without any
substitution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "contract" / "scenarios"

_ID_FIELDS = {"session_id", "task_id", "user_id", "target_task_id"}


def load_trace(filename: str) -> list[dict[str, Any]]:
    data = json.loads((SCENARIOS_DIR / filename).read_text())
    return data["trace"]


def _normalize(event: dict) -> dict:
    """Drop id fields and unset-vs-null noise so content comparisons focus
    on what the scenario actually says/decides."""
    return {k: v for k, v in event.items() if k not in _ID_FIELDS and v is not None}


def split_connections(trace: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Break a trace into per-WebSocket-connection chunks, splitting right
    after each session_end (a hangup/reconnect boundary)."""
    connections: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for entry in trace:
        current.append(entry)
        if entry["direction"] == "voice_to_agent" and entry["event"]["type"] == "session_end":
            connections.append(current)
            current = []
    if current:
        connections.append(current)
    return connections


def run_single_connection(ws, entries: list[dict[str, Any]]) -> str | None:
    task_id_actual: str | None = None
    for entry in entries:
        if entry["direction"] == "voice_to_agent":
            out = dict(entry["event"])
            if task_id_actual:
                if out.get("task_id"):
                    out["task_id"] = task_id_actual
                if "target_task_id" in out and out["target_task_id"]:
                    out["target_task_id"] = task_id_actual
            ws.send_json(out)
        else:
            actual = ws.receive_json()
            if task_id_actual is None and actual.get("task_id"):
                task_id_actual = actual["task_id"]
            expected = entry["event"]
            assert _normalize(actual) == _normalize(expected), (
                f"event mismatch\n  expected: {expected}\n  actual:   {actual}"
            )
    return task_id_actual


def run_full_trace(client, trace: list[dict[str, Any]]) -> None:
    for chunk in split_connections(trace):
        with client.websocket_connect("/v1/ws") as ws:
            run_single_connection(ws, chunk)
