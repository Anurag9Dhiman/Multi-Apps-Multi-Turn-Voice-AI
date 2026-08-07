import pytest
from pydantic import ValidationError

from voice_service.config import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_key")
    monkeypatch.setenv("CARTESIA_API_KEY", "ca_key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an_key")

    settings = Settings(_env_file=None)

    assert settings.deepgram_api_key == "dg_key"
    assert settings.cartesia_api_key == "ca_key"
    assert settings.anthropic_api_key == "an_key"


def test_collectiveos_ws_url_defaults_to_local_mock_backend(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg_key")
    monkeypatch.setenv("CARTESIA_API_KEY", "ca_key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an_key")
    monkeypatch.delenv("COLLECTIVEOS_WS_URL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.collectiveos_ws_url == "ws://localhost:8000/v1/ws"


def test_settings_fail_fast_lists_every_missing_key(monkeypatch):
    for key in ("DEEPGRAM_API_KEY", "CARTESIA_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    # loc uses each field's validation_alias (the env var name), not the
    # Python attribute name.
    missing = {e["loc"][0] for e in exc_info.value.errors()}
    assert missing == {"DEEPGRAM_API_KEY", "CARTESIA_API_KEY", "ANTHROPIC_API_KEY"}
