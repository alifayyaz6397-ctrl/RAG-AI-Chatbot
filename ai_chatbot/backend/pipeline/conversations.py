"""
conversations.py -- read APIs over the conversations table.

Two access levels:
  * a user reads their own conversations (scoped by user_id AND tenant_id)
  * an admin reads any user's, but still only inside their own tenant

Historical rows carry two typos that were written into the JSON before they
were fixed: the role "assisstant" and the key "retrived_chunk_id". Rewriting
139 stored rows to fix that is a migration, not a read path, so the normaliser
below accepts both spellings and always emits the correct one.
"""

from storage import get_connection

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

_ROLE_ALIASES = {"assisstant": "assistant"}
_CHUNK_KEYS = ("retrieved_chunk_id", "retrived_chunk_id")


def _chunk_ids(message: dict) -> list:
    for key in _CHUNK_KEYS:
        value = message.get(key)
        if isinstance(value, list):
            return value
    return []


def _normalise_messages(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    messages = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        message = {
            "role": _ROLE_ALIASES.get(role, role),
            "content": item.get("content"),
            "retrieved_chunk_ids": _chunk_ids(item),
        }
        # instructor-mode turns carry the routed intent and its result table
        for extra in ("intent", "confidence", "data"):
            if extra in item:
                message[extra] = item[extra]
        messages.append(message)
    return messages


def _clamp_paging(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    return page, page_size, (page - 1) * page_size


# A conversation summary never includes the full message list -- the preview is
# the first user turn, truncated, so a list of 100 conversations stays small.
# jsonb_array_elements() errors on a non-array, so both the count and the
# preview are guarded -- one malformed row should not break the whole page.
_SUMMARY_COLUMNS = """
    c.id, c.user_id, c.role, c.mode, c.rating, c.escalated, c.created_at,
    CASE WHEN jsonb_typeof(c.messages) = 'array'
         THEN jsonb_array_length(c.messages) ELSE 0 END AS message_count,
    CASE WHEN jsonb_typeof(c.messages) = 'array'
         THEN LEFT((SELECT m ->> 'content'
                    FROM jsonb_array_elements(c.messages) m
                    WHERE m ->> 'role' = 'user'
                    LIMIT 1), 200)
    END AS preview
"""


def _summary_row(r) -> dict:
    return {
        "id": r[0],
        "user_id": r[1],
        "role": r[2],
        "mode": r[3],
        "rating": r[4],
        "escalated": r[5],
        "created_at": r[6].isoformat() if r[6] else None,
        "message_count": r[7],
        "preview": r[8],
    }


def list_conversations(user, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                       mode: str | None = None) -> dict:
    """The caller's own conversations, newest first."""
    page, page_size, offset = _clamp_paging(page, page_size)
    params = {
        "user_id": user["linked_id"],
        "tenant_id": user["tenant_id"],
        "mode": mode,
        "limit": page_size,
        "offset": offset,
    }
    where = """
        WHERE c.user_id = %(user_id)s
          AND c.tenant_id = %(tenant_id)s
          AND (%(mode)s::text IS NULL OR c.mode = %(mode)s)
    """

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM conversations c {where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"""SELECT {_SUMMARY_COLUMNS}
                FROM conversations c
                {where}
                ORDER BY c.created_at DESC NULLS LAST, c.id DESC
                LIMIT %(limit)s OFFSET %(offset)s""",
            params,
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return {
        "conversations": [_summary_row(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": offset + len(rows) < total,
    }


def get_conversation(user, conversation_id: str) -> dict | None:
    """One conversation with its full message list. Returns None when the
    conversation does not exist OR belongs to somebody else -- the caller turns
    both into the same 404 so this can't be used to probe for valid ids.

    Admins may read any conversation inside their own tenant.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, user_id, role, mode, rating, escalated, created_at,
                      tenant_id, messages
               FROM conversations
               WHERE id = %s""",
            (conversation_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if row is None:
        return None

    (conv_id, user_id, role, mode, rating, escalated,
     created_at, tenant_id, messages) = row

    if tenant_id != user["tenant_id"]:
        return None
    if user["role"] != "admin" and user_id != user["linked_id"]:
        return None

    normalised = _normalise_messages(messages)
    all_chunk_ids = [
        chunk_id
        for message in normalised
        for chunk_id in message["retrieved_chunk_ids"]
    ]

    return {
        "id": conv_id,
        "user_id": user_id,
        "role": role,
        "mode": mode,
        "rating": rating,
        "escalated": escalated,
        "created_at": created_at.isoformat() if created_at else None,
        "messages": normalised,
        "retrieved_chunk_ids": all_chunk_ids,
    }


def list_all_conversations(user, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
                           user_id: str | None = None, role: str | None = None,
                           mode: str | None = None,
                           escalated: bool | None = None) -> dict:
    """Admin view: any user's conversations, still fenced to the admin's own
    tenant. Role check belongs to the route, but is repeated here so this
    function is not dangerous if called from somewhere else later."""
    if user["role"] != "admin":
        raise PermissionError("Only admins can list all conversations")

    page, page_size, offset = _clamp_paging(page, page_size)
    params = {
        "tenant_id": user["tenant_id"],
        "user_id": user_id,
        "role": role,
        "mode": mode,
        "escalated": escalated,
        "limit": page_size,
        "offset": offset,
    }
    where = """
        WHERE c.tenant_id = %(tenant_id)s
          AND (%(user_id)s::text IS NULL   OR c.user_id = %(user_id)s)
          AND (%(role)s::text IS NULL      OR c.role = %(role)s)
          AND (%(mode)s::text IS NULL      OR c.mode = %(mode)s)
          AND (%(escalated)s::boolean IS NULL
               OR COALESCE(c.escalated, false) = %(escalated)s)
    """

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM conversations c {where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"""SELECT {_SUMMARY_COLUMNS}
                FROM conversations c
                {where}
                ORDER BY c.created_at DESC NULLS LAST, c.id DESC
                LIMIT %(limit)s OFFSET %(offset)s""",
            params,
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return {
        "conversations": [_summary_row(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": offset + len(rows) < total,
    }
