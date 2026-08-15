"""Env-driven settings for the speech plugins and the LLM provider. Fails
fast with one combined error listing every missing key, rather than
letting each plugin raise its own ValueError one at a time as it happens
to be constructed.

Deliberately doesn't include LIVEKIT_URL/API_KEY/API_SECRET: WorkerOptions
already reads those itself with its own env fallback and only needs them
once a job connects to a real room, not for `console` mode (which runs a
simulated local job and needs no LiveKit account at all). Requiring them
here would block the fastest test path for no reason -- it did, in fact,
until this was noticed.

LLM provider: Anthropic (Claude Haiku) is the designed default for the
router and ack generator, but not a hard requirement -- ANTHROPIC_API_KEY
and GEMINI_API_KEY are each optional individually; at least one of the two
must be present. Gemini support exists specifically because a live
Anthropic key isn't always available (see gemini_client.py's adapter,
which lets router.py/ack.py stay provider-agnostic).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deepgram_api_key: str = Field(validation_alias="DEEPGRAM_API_KEY")
    cartesia_api_key: str = Field(validation_alias="CARTESIA_API_KEY")

    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-flash-latest", validation_alias="GEMINI_MODEL")

    # Explicit override for when both keys happen to be set. Unset means
    # "pick whichever one key is actually present"; if both are present
    # with no override, Anthropic wins -- it's the designed default,
    # Gemini is the fallback, not the other way around.
    llm_provider: Literal["anthropic", "gemini"] | None = Field(
        default=None, validation_alias="LLM_PROVIDER"
    )

    # Points at mock-agent-backend by default (its own default port) --
    # override to point at real CollectiveOS once it exists.
    collectiveos_ws_url: str = Field(
        default="ws://localhost:8000/v1/ws", validation_alias="COLLECTIVEOS_WS_URL"
    )

    # None -> session state (active tasks, entity stack) lives in-process
    # only, lost on restart. Set to use Redis (plan sec. 6); RedisSessionStore
    # is structurally complete but unverified -- no Redis instance exists in
    # this environment.
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")

    @model_validator(mode="after")
    def _require_at_least_one_llm_key(self) -> Settings:
        if not self.anthropic_api_key and not self.gemini_api_key:
            raise ValueError(
                "at least one of ANTHROPIC_API_KEY or GEMINI_API_KEY is required"
            )
        return self

    @property
    def resolved_llm_provider(self) -> Literal["anthropic", "gemini"]:
        if self.llm_provider:
            return self.llm_provider
        if self.gemini_api_key and not self.anthropic_api_key:
            return "gemini"
        if self.anthropic_api_key and not self.gemini_api_key:
            return "anthropic"
        return "anthropic"  # both set, no explicit choice -> designed default
