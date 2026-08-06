"""Pydantic models for the voice <-> CollectiveOS event contract (v1).

Mirrors ../../../../contract/schemas/*.schema.json. Keep the two in sync by
hand — there's no codegen step for the MVP, and the JSON Schemas remain the
source of truth other languages (a future TypeScript client) would target.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

RouterClass = Literal[
    "small_talk",
    "simple_lookup",
    "new_intent",
    "modify_inflight",
    "confirmation_reply",
    "session_query",
]

Priority = Literal["low", "high"]
RiskClass = Literal["read", "write"]
Decision = Literal["approve", "reject", "modify"]
TaskStatus = Literal[
    "pending",
    "planning",
    "running",
    "waiting",
    "blocked",
    "cancelled",
    "completed",
    "failed",
]
WaitingReason = Literal["user_confirm", "user_clarify", "external"] | None
Outcome = Literal["completed", "partial", "failed"]


# ---- voice layer -> CollectiveOS -------------------------------------------------


class SessionStart(BaseModel):
    type: Literal["session_start"] = "session_start"
    session_id: str
    user_id: str
    resume: bool


class UserUtterance(BaseModel):
    type: Literal["user_utterance"] = "user_utterance"
    session_id: str
    text: str
    router_class: RouterClass
    entity_refs: dict = Field(default_factory=dict)
    ts: str


class Interrupt(BaseModel):
    type: Literal["interrupt"] = "interrupt"
    session_id: str
    target_task_id: str | None
    text: str


class ConfirmationResponse(BaseModel):
    type: Literal["confirmation_response"] = "confirmation_response"
    session_id: str
    task_id: str
    decision: Decision
    modification: str | None = None


class SessionQuery(BaseModel):
    type: Literal["session_query"] = "session_query"
    session_id: str
    query: str


class SessionEnd(BaseModel):
    type: Literal["session_end"] = "session_end"
    session_id: str


VoiceToAgentEvent = Annotated[
    Union[
        SessionStart,
        UserUtterance,
        Interrupt,
        ConfirmationResponse,
        SessionQuery,
        SessionEnd,
    ],
    Field(discriminator="type"),
]


_voice_to_agent_adapter: TypeAdapter[VoiceToAgentEvent] = TypeAdapter(VoiceToAgentEvent)


def parse_voice_to_agent(raw: dict) -> VoiceToAgentEvent:
    return _voice_to_agent_adapter.validate_python(raw)


# ---- CollectiveOS -> voice layer -------------------------------------------------


class Ack(BaseModel):
    type: Literal["ack"] = "ack"
    task_id: str
    text: str


class Progress(BaseModel):
    type: Literal["progress"] = "progress"
    task_id: str
    text: str
    priority: Priority = "low"


class ConfirmationRequest(BaseModel):
    type: Literal["confirmation_request"] = "confirmation_request"
    task_id: str
    priority: Literal["high"] = "high"
    speak: str
    options: list[Decision]
    risk_class: RiskClass


class ClarificationRequest(BaseModel):
    type: Literal["clarification_request"] = "clarification_request"
    task_id: str
    priority: Literal["high"] = "high"
    speak: str


class TaskStep(BaseModel):
    tool: str
    risk_class: RiskClass


class TaskUpdate(BaseModel):
    type: Literal["task_update"] = "task_update"
    task_id: str
    status: TaskStatus
    waiting_reason: WaitingReason = None
    step: TaskStep | None = None


class Speak(BaseModel):
    type: Literal["speak"] = "speak"
    task_id: str
    text: str
    priority: Priority = "low"


class Done(BaseModel):
    type: Literal["done"] = "done"
    task_id: str
    outcome: Outcome
    summary_speak: str


class Error(BaseModel):
    type: Literal["error"] = "error"
    task_id: str
    recoverable: bool
    speak: str


AgentToVoiceEvent = Annotated[
    Union[
        Ack,
        Progress,
        ConfirmationRequest,
        ClarificationRequest,
        TaskUpdate,
        Speak,
        Done,
        Error,
    ],
    Field(discriminator="type"),
]


def dump_agent_event(event: AgentToVoiceEvent) -> dict:
    """Serialize for the wire, matching schemas/agent_to_voice.schema.json:
    optional fields (e.g. TaskUpdate.step) are omitted when unset rather
    than sent as null, since the schema types them as object-or-absent, not
    nullable. waiting_reason is the one field that's required *and*
    nullable, so it's always kept even when None.
    """
    data = event.model_dump(exclude_none=True)
    if isinstance(event, TaskUpdate):
        data["waiting_reason"] = event.waiting_reason
    return data
