import asyncio

from voice_service.session_store import InMemorySessionStore, SessionSnapshot


def test_load_missing_user_returns_none():
    store = InMemorySessionStore()

    result = asyncio.run(store.load("nobody"))

    assert result is None


def test_save_then_load_round_trips():
    store = InMemorySessionStore()
    snapshot = SessionSnapshot(
        user_id="u1",
        active_task_ids=["t1", "t2"],
        entity_stack=[{"label": "Acme Gym", "entity_id": "mention_acme_gym"}],
    )

    async def scenario():
        await store.save(snapshot)
        return await store.load("u1")

    loaded = asyncio.run(scenario())

    assert loaded == snapshot


def test_save_overwrites_previous_snapshot_for_same_user():
    store = InMemorySessionStore()

    async def scenario():
        await store.save(SessionSnapshot(user_id="u1", active_task_ids=["t1"]))
        await store.save(SessionSnapshot(user_id="u1", active_task_ids=["t2"]))
        return await store.load("u1")

    loaded = asyncio.run(scenario())

    assert loaded.active_task_ids == ["t2"]
