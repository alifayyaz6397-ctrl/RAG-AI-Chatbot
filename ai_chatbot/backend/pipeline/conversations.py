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
  # c.id, c.user_id, c.role, c.mode, c.rating, c.escalated, c.created_at,
    # CASE WHEN jsonb_typeof(c.messages) = 'array'
    #      THEN jsonb_array_length(c.messages) ELSE 0 END AS message_count,
    # CASE WHEN jsonb_typeof(c.messages) = 'array'
    #      THEN LEFT((SELECT m ->> 'content'
    #                 FROM jsonb_array_elements(c.messages) m
    #                 WHERE m ->> 'role' = 'user' AND m->> 'role' = 'assistant'
    #                 LIMIT 1), 200)
    # END AS preview
_SUMMARY_COLUMNS = """
    c.id, c.user_id, c.role, c.mode, c.rating, c.escalated, c.created_at,c.session_id,
  CASE WHEN jsonb_typeof(c.messages) = 'array'
       THEN jsonb_array_length(c.messages) ELSE 0 END AS message_count,
  CASE WHEN jsonb_typeof(c.messages) = 'array'
       THEN LEFT((SELECT m ->> 'content'
                  FROM jsonb_array_elements(c.messages) m
                  WHERE m ->> 'role' = 'user'
                  LIMIT 1), 200)
  END AS question_preview,
  CASE WHEN jsonb_typeof(c.messages) = 'array'
       THEN LEFT((SELECT m ->> 'content'
                  FROM jsonb_array_elements(c.messages) m
                  WHERE m ->> 'role' = 'assistant'
                  LIMIT 1), 200)
  END AS answer_preview

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
        "message_count": r[8],
        "question_preview": r[9],
        "answer_preview": r[10],
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
        
        import math
        max_page = max(1, math.ceil(total / page_size)) if total else 1
        if page > max_page:
            page = max_page
            offset = (page - 1) * page_size
            params["offset"] = offset

        cur.execute(
            f"""SELECT {_SUMMARY_COLUMNS},s.title
                FROM conversations c
                Left join session_titles s on c.session_id=s.session_id
                {where}
                ORDER BY c.created_at DESC NULLS LAST, c.id DESC
                LIMIT %(limit)s OFFSET %(offset)s""",
            params,
        )
        rows = cur.fetchall()
     
        cur.close()
        
        sessions = {}
        for row in rows:
            sid = row[7]

            if sid not in sessions:
                sessions[sid] = {
                    "session_id": sid,
                    "title": row[11],
                    "started_at": row[6],
                    "user_id": row[1],
                    "role": row[2],
                    "conversations": [],
                }

            

            sessions[sid]["conversations"].append({
                "id": row[0],
                "mode": row[3],
                "rating": row[4],
                "escalated": row[5],
                "created_at": row[6],
                "question": row[9],
                "answer": row[10]
            })
        for s in sessions.values():
                s["conversations"].sort(key=lambda c: c["created_at"],reverse=True)
                s["message_count"] = len(s["conversations"])
                s["started_at"] = s["conversations"][0]["created_at"]
                
            # order sessions newest-first (matches the row query's ORDER BY),
            # then relabel outer keys as "session 1", "session 2", ...
        
        result = list(sessions.values())
     
    finally:
            conn.close()

    return result;


def get_conversation(user, session_id: str) -> dict | None:
    """One conversation with its full message list. Returns None when the
    conversation does not exist OR belongs to somebody else -- the caller turns
    both into the same 404 so this can't be used to probe for valid ids.

    Admins may read any conversation inside their own tenant.
    """
    # The WHERE clause used to be `session_id = %s` and nothing else, so any
    # caller holding (or guessing) a session id could read another student's
    # chat -- the docstring above described a check the SQL did not perform.
    # A non-admin is now fenced to their own rows; an admin to their tenant.
    params = {
        "session_id": session_id,
        "tenant_id": user["tenant_id"],
        # NULL disables the owner test, which is how an admin reads any user's
        # conversation while staying inside their own tenant.
        "user_id": None if user["role"] == "admin" else user["linked_id"],
    }

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
    """SELECT c.id,c.created_at,
              CASE WHEN jsonb_typeof(c.messages) = 'array'
                   THEN (SELECT m ->> 'content'
                         FROM jsonb_array_elements(c.messages) m
                         WHERE m ->> 'role' = 'user'
                         LIMIT 1)
              END AS question_preview,
              CASE WHEN jsonb_typeof(c.messages) = 'array'
                   THEN (SELECT m ->> 'content'
                         FROM jsonb_array_elements(c.messages) m
                         WHERE m ->> 'role' = 'assistant'
                         LIMIT 1)
              END AS answer_preview
       FROM conversations c
       WHERE c.session_id = %(session_id)s
         AND c.tenant_id = %(tenant_id)s
         AND (%(user_id)s::text IS NULL OR c.user_id = %(user_id)s)
       ORDER BY c.created_at ASC""",
    params,
)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    # No rows means "does not exist" and "not yours" alike -- the route turns
    # both into the same 404 so this cannot enumerate other users' sessions.
    if not rows:
        return None

    return [
        {
            "id": row[0],
            "created_at": row[1],
            "question": row[2],
            "answer": row[3],
        }
        for row in rows
    ]


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
def store_rating(rating, conv_id):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE conversations SET rating = %s WHERE id = %s",
            (rating, conv_id)
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def suggesation_qns(role):
    conn =get_connection();
    try:
        cur=conn.cursor();
        cur.execute("select question ,role from suggestion_qns where role=%s",(role,))
        rows=cur.fetchall()
        cur.close;
    finally:
        conn.close()
    response=[]
    for row in rows:
        response.append({
        "question":row[0],
        "role":row[1]
    })
    return response