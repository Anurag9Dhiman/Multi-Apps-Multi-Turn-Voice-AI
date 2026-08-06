"""Every event in every reference scenario fixture must validate against
the frozen JSON Schemas in contract/schemas/ -- this is what keeps the
fixtures, the schemas, and the pydantic models in contract.py from drifting
apart silently.
"""

import json

import pytest
from jsonschema import Draft202012Validator

from ._util import SCENARIOS_DIR

SCHEMAS_DIR = SCENARIOS_DIR.parent / "schemas"

VOICE_TO_AGENT_SCHEMA = json.loads((SCHEMAS_DIR / "voice_to_agent.schema.json").read_text())
AGENT_TO_VOICE_SCHEMA = json.loads((SCHEMAS_DIR / "agent_to_voice.schema.json").read_text())

FIXTURES = sorted(SCENARIOS_DIR.glob("*.json"))


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_events_match_contract(fixture_path):
    trace = json.loads(fixture_path.read_text())["trace"]
    voice_validator = Draft202012Validator(VOICE_TO_AGENT_SCHEMA)
    agent_validator = Draft202012Validator(AGENT_TO_VOICE_SCHEMA)

    for i, entry in enumerate(trace):
        validator = voice_validator if entry["direction"] == "voice_to_agent" else agent_validator
        errors = list(validator.iter_errors(entry["event"]))
        assert not errors, (
            f"{fixture_path.name}[{i}] ({entry['event'].get('type')}) failed schema: "
            f"{[e.message for e in errors]}"
        )
