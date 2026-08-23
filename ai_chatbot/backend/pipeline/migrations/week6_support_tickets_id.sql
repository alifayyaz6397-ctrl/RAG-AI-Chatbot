-- Week 6 -- make support_tickets insertable.
--
-- support_tickets.id is a NOT NULL varchar primary key with no default, so
-- every INSERT had to invent an id. Nothing had ever written to the table
-- (0 rows), so this was untested. Confidence-based escalation now writes to
-- it, so it gets the same generated-id treatment conversations.id already
-- uses: 'ticket-001', 'ticket-002', ...
--
-- Idempotent: safe to re-run.

CREATE SEQUENCE IF NOT EXISTS support_tickets_id_seq;

ALTER TABLE support_tickets
    ALTER COLUMN id SET DEFAULT ('ticket-' || lpad(nextval('support_tickets_id_seq')::text, 3, '0'));

-- Keep the sequence ahead of anything already in the table. The third
-- argument is is_called: false on an empty table so numbering starts at
-- ticket-001 rather than ticket-002.
SELECT setval(
    'support_tickets_id_seq',
    GREATEST((SELECT COALESCE(MAX(NULLIF(regexp_replace(id, '\D', '', 'g'), ''))::bigint, 0)
              FROM support_tickets), 1),
    (SELECT COUNT(*) > 0 FROM support_tickets)
);

-- The dedupe check on escalation looks up open tickets per user.
CREATE INDEX IF NOT EXISTS support_tickets_user_status_idx
    ON support_tickets (user_id, status);
