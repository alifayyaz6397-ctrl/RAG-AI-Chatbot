-- Week 6 -- per-message feedback.
--
-- Individual messages have no primary key of their own: they live inside the
-- `conversations.messages` jsonb array. So a message is addressed by the pair
-- (conversation_id, message_index), and `message_id` is the human-readable
-- composite of those two -- e.g. 'conv-140:1'. Both forms are stored: the
-- composite because the API and the report talk in terms of a message_id, the
-- split columns because that is what you can actually JOIN and index on.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS message_feedback (
    id              SERIAL PRIMARY KEY,
    message_id      VARCHAR(80)  NOT NULL,
    conversation_id VARCHAR      NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_index   INTEGER      NOT NULL CHECK (message_index >= 0),
    user_id         VARCHAR      NOT NULL,
    tenant_id       VARCHAR      NOT NULL DEFAULT 'uet_default',
    rating          VARCHAR(10)  NOT NULL CHECK (rating IN ('up', 'down')),
    comment         TEXT,
    created_at      TIMESTAMP    DEFAULT now(),
    updated_at      TIMESTAMP    DEFAULT now(),

    -- One vote per user per message. Re-submitting updates the existing row
    -- rather than stacking duplicate votes and skewing the review queue.
    CONSTRAINT message_feedback_one_vote_per_user UNIQUE (message_id, user_id)
);

-- The review queue filters on rating and joins back to the conversation.
CREATE INDEX IF NOT EXISTS message_feedback_conversation_idx
    ON message_feedback (conversation_id);
CREATE INDEX IF NOT EXISTS message_feedback_rating_idx
    ON message_feedback (rating);
CREATE INDEX IF NOT EXISTS message_feedback_tenant_idx
    ON message_feedback (tenant_id);
