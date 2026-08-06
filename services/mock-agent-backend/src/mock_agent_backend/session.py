"""In-memory session/task state so a resumed connection can pick up where a
previous one left off. Good enough for the mock backend's scripted scenarios
and their tests; CollectiveOS's real implementation persists this in
Postgres (`tasks`, `tasks.waiting_reason`) per the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NON_TERMINAL_STATUSES = {"pending", "planning", "running", "waiting", "blocked"}


@dataclass
class TaskRecord:
    task_id: str
    user_id: str
    scenario: str
    status: str = "pending"
    waiting_reason: str | None = None


@dataclass
class SessionRecord:
    session_id: str
    user_id: str
    resume: bool


@dataclass
class Store:
    """Keyed by user_id so a resumed session (new session_id) can find the
    task a previous session left mid-flight."""

    tasks_by_user: dict[str, dict[str, TaskRecord]] = field(default_factory=dict)

    def put_task(self, task: TaskRecord) -> None:
        self.tasks_by_user.setdefault(task.user_id, {})[task.task_id] = task

    def non_terminal_tasks_for(self, user_id: str) -> list[TaskRecord]:
        return [
            t
            for t in self.tasks_by_user.get(user_id, {}).values()
            if t.status in NON_TERMINAL_STATUSES
        ]


STORE = Store()
