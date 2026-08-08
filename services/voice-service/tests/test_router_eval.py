import asyncio

from voice_service.router_eval import LABELED_UTTERANCES, run_eval


def test_dataset_covers_all_six_router_classes_evenly():
    classes = [expected for _, expected, _ in LABELED_UTTERANCES]
    assert set(classes) == {
        "small_talk",
        "simple_lookup",
        "new_intent",
        "modify_inflight",
        "confirmation_reply",
        "session_query",
    }
    for cls in set(classes):
        assert classes.count(cls) >= 3, f"{cls} is underrepresented"


def test_perfect_classifier_scores_100_percent():
    async def perfect_classify(text, *, has_active_task=False):
        for t, expected, _ in LABELED_UTTERANCES:
            if t == text:
                return expected
        raise AssertionError(f"unexpected text: {text!r}")

    result = asyncio.run(run_eval(perfect_classify))

    assert result.accuracy == 1.0
    assert result.misclassifications == []


def test_misclassifications_are_reported_with_expected_and_actual():
    async def always_small_talk(text, *, has_active_task=False):
        return "small_talk"

    result = asyncio.run(run_eval(always_small_talk))

    assert result.correct < result.total
    assert all(actual == "small_talk" for _, _, actual in result.misclassifications)
    report = result.report()
    assert "MISS" in report
    assert f"{result.correct}/{result.total}" in report
