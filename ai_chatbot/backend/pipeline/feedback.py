"""
feedback.py -- per-message thumbs up/down and the admin review queue.

A message has no id of its own (messages are elements of the
`conversations.messages` jsonb array), so a message is addressed as
"<conversation_id>:<message_index>", e.g. "conv-140:1". parse_message_id()
is the single place that format is understood.

The review queue answers the question the week-6 brief actually asks: not
"which answers were bad" but "which knowledge-base document is weak". It does
that by walking from a down-vote to the chunks that answer cited, and from
those chunks to their source document.
"""

import re

from storage import get_connection

VALID_RATINGS = ("up", "down")
MAX_COMMENT_LENGTH = 2000

_MESSAGE_ID_RE = re.compile(r"^(?P<conversation_id>[A-Za-z0-9_-]+):(?P<index>\d+)$")


class FeedbackError(Exception):
    """Bad request from the caller -- surfaced as a 400."""


def parse_message_id(message_id: str) -> tuple[str, int]:
    match = _MESSAGE_ID_RE.match((message_id or "").strip())
    if not match:
        raise FeedbackError(
            "message_id must look like '<conversation_id>:<message_index>', e.g. 'conv-140:1'"
        )
    return match.group("conversation_id"), int(match.group("index"))


# Both spellings of the chunk-id key appear in stored rows (the typo
# "retrived_chunk_id" predates the fix), and some early rows recorded cosine
# distances instead of ids -- hence the '^\d+$' filter before casting.
_CITED_CHUNKS = r"""
    jsonb_array_elements_text(
        CASE WHEN jsonb_typeof(COALESCE(msg -> 'retrieved_chunk_id',
                                        msg -> 'retrived_chunk_id')) = 'array'
             THEN COALESCE(msg -> 'retrieved_chunk_id', msg -> 'retrived_chunk_id')
             ELSE '[]'::jsonb END
    )
"""


def submit_feedback(user, message_id: str, rating: str, comment: str | None = None) -> dict:
    """Record (or update) this user's vote on one message.

    The message must exist, must belong to a conversation the caller may see,
    and must be an assistant turn -- rating your own question is meaningless
    and would pollute the review queue.
    """
    if rating not in VALID_RATINGS:
        raise FeedbackError(f"rating must be one of: {', '.join(VALID_RATINGS)}")
    if comment is not None and len(comment) > MAX_COMMENT_LENGTH:
        raise FeedbackError(f"comment must be {MAX_COMMENT_LENGTH} characters or fewer")

    conversation_id, message_index = parse_message_id(message_id)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT user_id, tenant_id,
                      CASE WHEN jsonb_typeof(messages) = 'array'
                           THEN jsonb_array_length(messages) ELSE 0 END,
                      messages -> %s ->> 'role'
               FROM conversations
               WHERE id = %s""",
            (message_index, conversation_id),
        )
        row = cur.fetchone()

        # Same collapse as the conversation read path: "not yours" and "does
        # not exist" are one answer, so this can't enumerate conversation ids.
        if row is None:
            raise FeedbackError("Message not found")

        owner_id, tenant_id, message_count, role = row
        if tenant_id != user["tenant_id"]:
            raise FeedbackError("Message not found")
        if user["role"] != "admin" and owner_id != user["linked_id"]:
            raise FeedbackError("Message not found")
        if message_index >= message_count:
            raise FeedbackError("Message not found")

        # 'assisstant' is the legacy typo, still present in older rows.
        if role not in ("assistant", "assisstant"):
            raise FeedbackError("Feedback can only be given on an assistant message")

        cur.execute(
            """INSERT INTO message_feedback
                   (message_id, conversation_id, message_index, user_id,
                    tenant_id, rating, comment)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (message_id, user_id) DO UPDATE
                   SET rating = EXCLUDED.rating,
                       comment = EXCLUDED.comment,
                       updated_at = now()
               RETURNING id, created_at, updated_at""",
            (f"{conversation_id}:{message_index}", conversation_id, message_index,
             user["linked_id"], user["tenant_id"], rating, comment),
        )
        feedback_id, created_at, updated_at = cur.fetchone()
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return {
        "feedback_id": feedback_id,
        "message_id": f"{conversation_id}:{message_index}",
        "rating": rating,
        "comment": comment,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def review_queue(user, rating: str = "down", limit: int = 50) -> dict:
    """Admin review queue: low-rated answers rolled up by the chunk they cited,
    and then by the document those chunks came from.

    A document appearing high in `weak_documents` is the signal to go and
    improve that source material.
    """
    if user["role"] != "admin":
        raise PermissionError("Only admins can view the feedback review queue")
    if rating not in VALID_RATINGS:
        raise FeedbackError(f"rating must be one of: {', '.join(VALID_RATINGS)}")

    limit = max(1, min(limit, 200))
    params = {"tenant_id": user["tenant_id"], "rating": rating, "limit": limit}

    # Shared by all three result sets below: every rated message, paired with
    # each chunk id it cited.
    cited_cte = f"""
        WITH rated AS (
            SELECT f.id, f.rating, f.comment, f.user_id, f.message_id,
                   f.conversation_id, f.message_index, f.created_at,
                   c.messages -> f.message_index AS msg
            FROM message_feedback f
            JOIN conversations c ON c.id = f.conversation_id
            WHERE f.tenant_id = %(tenant_id)s
              AND f.rating = %(rating)s
              AND jsonb_typeof(c.messages) = 'array'
        ),
        cited AS (
            SELECT r.id AS feedback_id, r.conversation_id, chunk_id
            FROM rated r
            CROSS JOIN LATERAL {_CITED_CHUNKS} AS chunk_id
            WHERE chunk_id ~ '^\\d+$'
        )
    """

    conn = get_connection()
    try:
        cur = conn.cursor()

        # 1. Which chunks are attached to the most complaints
        cur.execute(cited_cte + """
            SELECT k.id,
                   LEFT(k.content, 240),
                   d.id,
                   d.filename,
                   COUNT(DISTINCT ct.feedback_id) AS negative_count
            FROM cited ct
            JOIN knowledge_chunks k ON k.id = ct.chunk_id::integer
            LEFT JOIN documents d ON d.id = k.document_id
            GROUP BY k.id, k.content, d.id, d.filename
            ORDER BY negative_count DESC, k.id
            LIMIT %(limit)s
        """, params)
        weak_chunks = [
            {"chunk_id": r[0], "chunk_preview": r[1], "document_id": r[2],
             "filename": r[3], "negative_count": r[4]}
            for r in cur.fetchall()
        ]

        # 2. The same complaints rolled up to the document
        cur.execute(cited_cte + """
            SELECT d.id,
                   d.filename,
                   COUNT(DISTINCT ct.feedback_id) AS negative_count,
                   COUNT(DISTINCT k.id)           AS chunks_implicated
            FROM cited ct
            JOIN knowledge_chunks k ON k.id = ct.chunk_id::integer
            LEFT JOIN documents d ON d.id = k.document_id
            GROUP BY d.id, d.filename
            ORDER BY negative_count DESC
            LIMIT %(limit)s
        """, params)
        weak_documents = [
            {"document_id": r[0], "filename": r[1],
             "negative_count": r[2], "chunks_implicated": r[3]}
            for r in cur.fetchall()
        ]

        # 3. The individual complaints, so an admin can read what was actually
        #    said. Answers citing no chunks still show up here -- those are the
        #    interesting ones for hallucination review.
        cur.execute("""
            SELECT f.id, f.message_id, f.conversation_id, f.message_index,
                   f.user_id, f.comment, f.created_at, c.mode,
                   LEFT(c.messages -> f.message_index ->> 'content', 300),
                   LEFT((SELECT m ->> 'content'
                         FROM jsonb_array_elements(c.messages) m
                         WHERE m ->> 'role' = 'user' LIMIT 1), 200)
            FROM message_feedback f
            JOIN conversations c ON c.id = f.conversation_id
            WHERE f.tenant_id = %(tenant_id)s
              AND f.rating = %(rating)s
              AND jsonb_typeof(c.messages) = 'array'
            ORDER BY f.created_at DESC
            LIMIT %(limit)s
        """, params)
        items = [
            {"feedback_id": r[0], "message_id": r[1], "conversation_id": r[2],
             "message_index": r[3], "user_id": r[4], "comment": r[5],
             "created_at": r[6].isoformat() if r[6] else None, "mode": r[7],
             "answer_preview": r[8], "question": r[9]}
            for r in cur.fetchall()
        ]

        cur.execute(
            """SELECT rating, COUNT(*) FROM message_feedback
               WHERE tenant_id = %(tenant_id)s GROUP BY rating""",
            params,
        )
        totals = {r[0]: r[1] for r in cur.fetchall()}
        cur.close()
    finally:
        conn.close()

    return {
        "rating": rating,
        "totals": {"up": totals.get("up", 0), "down": totals.get("down", 0)},
        "weak_documents": weak_documents,
        "weak_chunks": weak_chunks,
        "items": items,
    }
