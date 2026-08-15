"""Picks the LLM client for whichever provider is configured
(config.py's `resolved_llm_provider`) -- shared by agent.py and
router_eval.py so there's exactly one place that knows how to construct
either provider. A standalone module rather than living in agent.py: that
module pulls in LiveKit's full dependency chain, which router_eval.py (a
plain CLI script) has no reason to import just to reuse this.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic

from .config import Settings
from .gemini_client import GeminiMessagesClient
from .router import MessagesClient


def make_llm_client(settings: Settings) -> MessagesClient:
    """Shared by the router and ack generator -- both only need whichever
    provider is configured, not two separately-constructed clients."""
    if settings.resolved_llm_provider == "gemini":
        return GeminiMessagesClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return AsyncAnthropic(api_key=settings.anthropic_api_key).messages
