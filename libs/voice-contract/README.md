# voice-contract

Pydantic models for the voice-layer ↔ CollectiveOS event contract (v1) —
mirrors the JSON Schemas at [`/contract`](../../contract) at the repo root,
which remain the source of truth for other languages.

Depended on by both sides of the contract, as a local editable path
dependency (`uv add --editable ../../libs/voice-contract`):

- `services/mock-agent-backend` (plays CollectiveOS) parses
  `VoiceToAgentEvent`, dumps `AgentToVoiceEvent`
- `services/voice-service` (plays the voice layer) dumps
  `VoiceToAgentEvent`, parses `AgentToVoiceEvent`

One shared set of models instead of two hand-duplicated copies — the two
services would otherwise be free to drift apart silently.
