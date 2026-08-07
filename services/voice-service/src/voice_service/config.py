"""Env-driven settings for the speech plugins. Fails fast with one combined
error listing every missing key, rather than letting each plugin raise its
own ValueError one at a time as it happens to be constructed.

Deliberately doesn't include LIVEKIT_URL/API_KEY/API_SECRET: WorkerOptions
already reads those itself with its own env fallback and only needs them
once a job connects to a real room, not for `console` mode (which runs a
simulated local job and needs no LiveKit account at all). Requiring them
here would block the fastest test path for no reason -- it did, in fact,
until this was noticed.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deepgram_api_key: str = Field(validation_alias="DEEPGRAM_API_KEY")
    cartesia_api_key: str = Field(validation_alias="CARTESIA_API_KEY")
    anthropic_api_key: str = Field(validation_alias="ANTHROPIC_API_KEY")

    # Points at mock-agent-backend by default (its own default port) --
    # override to point at real CollectiveOS once it exists.
    collectiveos_ws_url: str = Field(
        default="ws://localhost:8000/v1/ws", validation_alias="COLLECTIVEOS_WS_URL"
    )
