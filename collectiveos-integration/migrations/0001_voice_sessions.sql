-- Additive migration for CollectiveOS (plan sec. 6 and sec. 10: "Open the
-- CollectiveOS integration branch early with just the additive migration
-- ... so the schema question is settled, even though integration itself
-- comes last"). Apply this inside the CollectiveOS repo, not here -- this
-- repo has no database of its own, and doesn't depend on this migration
-- to build or test anything (mock-agent-backend keeps its own in-memory
-- equivalent; see services/mock-agent-backend/src/mock_agent_backend/session.py).
--
-- Strictly additive, per the plan's own rule for this migration: a new
-- table, plus one new column with a safe default -- nothing existing
-- changes shape or meaning.

BEGIN;

CREATE TABLE voice_sessions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id),
    active_task_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    entity_stack    jsonb NOT NULL DEFAULT '[]'::jsonb,
    started_at      timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz
);

-- Lookups are always "does this user have an open/resumable session" --
-- the index that matters is user_id filtered to still-open sessions.
CREATE INDEX voice_sessions_open_by_user
    ON voice_sessions (user_id)
    WHERE ended_at IS NULL;

ALTER TABLE tasks
    ADD COLUMN waiting_reason text
        CHECK (waiting_reason IN ('user_confirm', 'user_clarify', 'external'));

COMMENT ON COLUMN tasks.waiting_reason IS
    'Set iff status is waiting (user_confirm/user_clarify) or blocked '
    '(external) -- tells the voice layer whether to speak-and-listen or '
    'merely narrate. NULL otherwise. See /contract/README.md in the '
    'voice platform repo for the full state machine this participates in.';

COMMIT;
