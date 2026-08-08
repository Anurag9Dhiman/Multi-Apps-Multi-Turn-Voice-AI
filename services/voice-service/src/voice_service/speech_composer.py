"""Speech composer (plan sec. 4a): event -> spoken text policy --
priority preemption (high cuts whatever's playing, low is dropped if the
user is mid-utterance) and the one-breath rule (flag anything too long to
say in one breath; this is a prosody judgment, not a hard character limit,
so it logs rather than truncates and mangles meaning).

Framework-agnostic on purpose, same reasoning as conversation.py: the
policy is what weeks 7-8 actually add, and it's what's testable without
LiveKit or live audio. agent.py supplies the two primitives
(`raw_speak`/`raw_interrupt`) that actually touch AgentSession.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from voice_contract import Priority

logger = logging.getLogger("voice_service.speech_composer")

# Soft guidance, not a hard limit: past this many words a line is unlikely
# to fit in one breath. Logged so the eval suite can track how often
# CollectiveOS or our own templates violate the rule, per plan sec. 1 rule 2.
ONE_BREATH_WORD_LIMIT = 25

RawSpeak = Callable[[str], Awaitable[object]]
RawInterrupt = Callable[[], Awaitable[None]]
IsUserSpeaking = Callable[[], bool]


class SpeechComposer:
    def __init__(
        self,
        *,
        raw_speak: RawSpeak,
        raw_interrupt: RawInterrupt,
        is_user_speaking: IsUserSpeaking,
    ) -> None:
        self._raw_speak = raw_speak
        self._raw_interrupt = raw_interrupt
        self._is_user_speaking = is_user_speaking

    async def speak(self, text: str, priority: Priority) -> object | None:
        _check_one_breath(text)

        if priority == "high":
            await self._raw_interrupt()
        elif self._is_user_speaking():
            logger.debug("dropping low-priority line, user is speaking: %r", text)
            return None

        return await self._raw_speak(text)


def _check_one_breath(text: str) -> None:
    words = len(text.split())
    if words > ONE_BREATH_WORD_LIMIT:
        logger.warning("line exceeds one-breath guidance (%d words): %r", words, text)
