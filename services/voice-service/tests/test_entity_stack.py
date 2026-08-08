from voice_service.entity_stack import EntityStack


def test_resolves_pronoun_to_most_recent_mention():
    stack = EntityStack()
    stack.observe_agent_speech("I can move the 9, 10, and 11 o'clock to Thursday.")

    refs = stack.resolve("wait, keep that one")

    assert refs == {"that one": "mention_11_o_clock"}


def test_no_mentions_means_no_resolution():
    stack = EntityStack()

    refs = stack.resolve("cancel it")

    assert refs == {}


def test_proper_noun_mentions_are_tracked():
    stack = EntityStack()
    stack.observe_agent_speech("Found four subscriptions: Acme Gym and Spotify.")

    refs = stack.resolve("keep that one")

    assert refs == {"that one": "mention_spotify"}


def test_sentence_initial_capitalized_words_are_not_treated_as_entities():
    stack = EntityStack()
    stack.observe_agent_speech("Checking your calendar now.")

    assert stack.snapshot() == []


def test_snapshot_and_restore_round_trip():
    stack = EntityStack()
    stack.observe_agent_speech("the 10am with Acme Gym")

    restored = EntityStack()
    restored.restore(stack.snapshot())

    assert restored.resolve("keep it") == stack.resolve("keep it")


def test_multiple_pronouns_in_one_utterance_all_resolve():
    stack = EntityStack()
    stack.observe_agent_speech("the 10am")

    refs = stack.resolve("keep it, not that one")

    assert refs == {"it": "mention_10am", "that one": "mention_10am"}
