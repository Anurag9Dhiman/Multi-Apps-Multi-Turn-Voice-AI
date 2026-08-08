import asyncio
import logging

from voice_service.speech_composer import ONE_BREATH_WORD_LIMIT, SpeechComposer


def _composer(*, user_speaking: bool = False):
    calls: list[str] = []
    interrupted = []

    async def raw_speak(text):
        calls.append(text)
        return object()

    async def raw_interrupt():
        interrupted.append(True)

    composer = SpeechComposer(
        raw_speak=raw_speak,
        raw_interrupt=raw_interrupt,
        is_user_speaking=lambda: user_speaking,
    )
    return composer, calls, interrupted


def test_high_priority_interrupts_before_speaking():
    composer, calls, interrupted = _composer()

    asyncio.run(composer.speak("Shall I go ahead?", "high"))

    assert interrupted == [True]
    assert calls == ["Shall I go ahead?"]


def test_low_priority_is_dropped_while_user_is_speaking():
    composer, calls, interrupted = _composer(user_speaking=True)

    result = asyncio.run(composer.speak("Found three meetings.", "low"))

    assert result is None
    assert calls == []
    assert interrupted == []


def test_low_priority_speaks_when_user_is_not_speaking():
    composer, calls, interrupted = _composer(user_speaking=False)

    asyncio.run(composer.speak("Found three meetings.", "low"))

    assert calls == ["Found three meetings."]
    assert interrupted == []


def test_one_breath_violation_is_logged_not_blocked(caplog):
    composer, calls, _ = _composer()
    long_text = " ".join(["word"] * (ONE_BREATH_WORD_LIMIT + 5))

    with caplog.at_level(logging.WARNING, logger="voice_service.speech_composer"):
        asyncio.run(composer.speak(long_text, "low"))

    assert calls == [long_text]  # still spoken -- this is a soft rule
    assert any("one-breath" in r.message for r in caplog.records)
