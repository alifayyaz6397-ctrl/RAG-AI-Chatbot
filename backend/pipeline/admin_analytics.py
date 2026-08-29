"""
admin_analytics.py -- free-form, read-only SQL for /api/admin/chat.

analytics.py deliberately keeps instructor queries as fixed, hand-written
templates -- Gemini never writes SQL there. Admins need more flexibility
(arbitrary tables, arbitrary questions), so this module gives them natural
language -> SQL instead. That flexibility needs its own guardrails, kept
entirely separate from the instructor path so the safety story for each
stays legible on its own:

  1. AdminScope       Built only from the verified JWT, same pattern as
                       Scope in analytics.py. Never anything the client or
                       the model produced.
  2. SCHEMA            The only tables the model is ever told exist. A
                       generated query may not reference anything outside
                       this list -- checked, not assumed.
  3. validate_sql()    Parses the model's SQL (via sqlglot, not regex) and
                       rejects anything that isn't a single, read-only
                       SELECT against an allowed table, with no disallowed
                       functions.
  4. run_admin_sql()   Executes the validated query with tenant_id bound as
                       a real parameterised value from AdminScope. The model
                       may reference a :tenant_id placeholder in its SQL,
                       but the value that fills it always comes from the
                       verified JWT, never from generated text.

Known limitation: this checks that a tenant-scoped table is *filtered* on
tenant_id somewhere in the query, but it can't prove the filter is applied
correctly to every joined table in every possible query shape. The durable
fix is Postgres row-level security keyed on the same session tenant_id, so a
query that gets the filter wrong still can't return another tenant's rows.
That's a DB-level change or the next step here, not a change to this file.
"""

import re

import sqlglot
from sqlglot import exp

from storage import get_connection

ALLOWED_ROLES = ("admin",)

# The only tables a generated query may reference, and the column lists
# handed to the model so it isn't guessing at names. `embedding` is left out
# of knowledge_chunks on purpose -- a large vector column with no reporting
# value and no reason to ever leave the database.
SCHEMA = {
    "students": "students(id, name, email, tenant_id, department_id, enrollment_year, semester_id)",
    "instructors": "instructors(id, name, email, department_id, tenant_id)",
    "admins": "admins(id, name, email, tenant_id)",
    "departments": (
        "departments(id, name, tenant_id) -- known rows: "
        "dept_cs='Computer Science', dept_se='Software Engineering', "
        "dept_ee='Electrical Engineering', dept_ai='Artificial Intelligence'. "
        "A question naming an abbreviation (CS, SE, EE, AI) means the "
        "matching id above, e.g. id = 'dept_cs' -- do not try to match the "
        "abbreviation against the name column, it will not appear there."
    ),
    "semesters": "semesters(id, name, start_date, end_date)",
    "exams": (
        "exams(id, title, subject, date, duration_minutes, status, "
        "department_id, semester_id, owner_instructor_id, tenant_id, "
        "start_at, end_at)"
    ),
    "enrollments": "enrollments(student_id, exam_id, enrolled_at)",
    "results": (
        "results(student_id, exam_id, score_percent, grade, "
        "certificate_available, section_breakdown [json keys: MCQ, "
        "ShortAnswer, LongAnswer], certificate_id)"
    ),
    "certificates": (
        "certificates(id, student_id, exam_id, verification_code, "
        "issued_at, tenant_id, grade, score_percent, status, remark)"
    ),
    "conversations": (
        "conversations(id, user_id, role, messages, rating, escalated, "
        "created_at, tenant_id, mode, session_id)"
    ),
    "message_feedback": (
        "message_feedback(id, message_id, conversation_id, message_index, "
        "user_id, tenant_id, rating, comment, created_at, updated_at)"
    ),
    "feedback": "feedback(id, conversation_id, user_id, rating, flagged_for_review)",
    "escalations": (
        "escalations(id, user_id, tenant_id, reason, question, status, created_at)"
    ),
    "support_tickets": (
        "support_tickets(id, conversation_id, user_id, reason, status, "
        "created_at, tenant_id)"
    ),
    "documents": "documents(id, filename, upload_date, document_type)",
    "knowledge_chunks": (
        "knowledge_chunks(id, source_document, chunk_index, content, "
        "created_at, document_id)"
    ),
    "session_titles": "session_titles(title, session_id)",
}

ALLOWED_TABLES = set(SCHEMA)

# Any table carrying a tenant_id column -- a generated query touching one of
# these must reference the :tenant_id placeholder somewhere.
TENANT_SCOPED_TABLES = {
    "students", "instructors", "admins", "departments", "exams",
    "certificates", "conversations", "message_feedback", "escalations",
    "support_tickets",
}

# Functions with no legitimate reporting use that read/write outside the
# rows sqlglot already validated -- blocked outright rather than allowlisted.
FORBIDDEN_FUNCS = {
    "pg_sleep", "pg_read_file", "pg_read_binary_file", "pg_ls_dir",
    "dblink", "lo_import", "lo_export",
}

DEFAULT_ROW_LIMIT = 200

class AdminAnalyticsError(Exception):
    """Raised for problems reported to the admin verbatim (an unsafe query,
    an empty result, a table that isn't available) rather than fed to the
    LLM as if it were data."""


class AdminScope:
    """Everything that limits what this caller may see. Built from the
    verified JWT only, same discipline as Scope in analytics.py."""

    def __init__(self, user):
        if user.get("role") not in ALLOWED_ROLES:
            raise AdminAnalyticsError("Free-form analytics are only available to admins.")
        self.tenant_id = user["tenant_id"]

    def as_params(self) -> dict:
        return {"tenant_id": self.tenant_id}


def schema_block() -> str:
    return "\n".join(f"- {v}" for v in SCHEMA.values())


def validate_sql(sql: str) -> str:
    """Parses the model's SQL and returns a cleaned, safe-to-run query
    string. Raises AdminAnalyticsError for anything that doesn't pass --
    this function is the only thing standing between generated text and
    execute()."""
    if not sql or not sql.strip():
        raise AdminAnalyticsError("No query was generated.")

    try:
        parsed = [p for p in sqlglot.parse(sql, read="postgres") if p is not None]
    except Exception as exc:  # sqlglot raises its own error types per-dialect
        raise AdminAnalyticsError(f"Generated SQL did not parse: {exc}") from exc

    if len(parsed) != 1:
        raise AdminAnalyticsError("Only a single statement is allowed.")

    stmt = parsed[0]
    if not isinstance(stmt, exp.Select):
        raise AdminAnalyticsError("Only SELECT statements are allowed.")

    used_tables = {t.name.lower() for t in stmt.find_all(exp.Table)}
    disallowed_tables = used_tables - ALLOWED_TABLES
    if disallowed_tables:
        raise AdminAnalyticsError(
            "Query references tables that aren't available: "
            + ", ".join(sorted(disallowed_tables))
        )

    used_funcs = {f.name.lower() for f in stmt.find_all(exp.Func) if f.name}
    bad_funcs = used_funcs & FORBIDDEN_FUNCS
    if bad_funcs:
        raise AdminAnalyticsError(
            "Query uses disallowed functions: " + ", ".join(sorted(bad_funcs))
        )

    if used_tables & TENANT_SCOPED_TABLES:
        if ":tenant_id" not in sql:
            raise AdminAnalyticsError(
                "Query touches tenant-scoped data but doesn't filter on tenant_id."
            )

    cleaned = stmt.sql(dialect="postgres")

    if not re.search(r"\bLIMIT\s+\d+\b", cleaned, re.IGNORECASE):
        cleaned = f"{cleaned} LIMIT {DEFAULT_ROW_LIMIT}"

    return cleaned


def run_admin_sql(scope: AdminScope, sql: str) -> dict:
    """Validates, then executes with tenant_id bound from `scope` -- never
    from the generated SQL text. The model may only place the :tenant_id
    placeholder; the value that fills it is always the verified one.

    sqlglot's postgres dialect renders a :tenant_id placeholder as
    %(tenant_id)s automatically (see validate_sql), which is exactly the
    named-parameter style psycopg2 expects -- no further string surgery
    needed here, and none should be added, since hand-editing the query
    text after validation is exactly what we're trying to avoid."""
    cleaned = validate_sql(sql)

    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(cleaned, scope.as_params())
        except Exception as exc:
            raise AdminAnalyticsError(f"The database rejected that query: {exc}") from exc
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()

    return {
        "intent": "admin_sql",
        "title": "Query result",
        "columns": columns,
        "rows": _jsonify(rows),
        "sql": cleaned,
    }


def _jsonify(rows: list[list]) -> list[list]:
    """Decimal/date -> float/str so rows survive json.dumps on the way to
    the report writer and out to the client, same as analytics.py."""
    out = []
    for row in rows:
        out.append([
            float(v) if hasattr(v, "as_tuple")
            else v.isoformat() if hasattr(v, "isoformat")
            else v
            for v in row
        ])
    return out


# ---------------------------------------------------------------------------
# Hand-written templates
# ---------------------------------------------------------------------------
# A handful of admin questions need aggregation shapes that free-form
# generation is least reliable at (here: unnesting a JSON array nested
# inside another JSON array, messages[].retrieved_chunk_id[]) and where
# getting it wrong fails silently -- zero rows, not an error, so a wrong
# query looks identical to "no data" to everyone downstream. Rather than
# trust generation with that, these are hand-written and parameterised,
# same discipline as analytics.py's instructor reports. generate_sql() in
# instructor.py picks one of these by name instead of writing SQL when the
# question matches; TEMPLATES is the only set of names it may pick from.

_DOCUMENT_CITATION_STATS_SQL = """
    WITH doc_count AS (
        SELECT COUNT(*) AS total_documents FROM documents
    ),
    citations AS (
        SELECT elem::int AS chunk_id
        FROM conversations c,
             jsonb_array_elements(c.messages) AS msg,
             jsonb_array_elements_text(msg->'retrieved_chunk_id') AS elem
        WHERE c.tenant_id = %(tenant_id)s
          AND jsonb_typeof(msg->'retrieved_chunk_id') = 'array'
          AND elem ~ '^[0-9]+$'
    ),
    chunk_counts AS (
        SELECT chunk_id, COUNT(*) AS times_cited
        FROM citations
        GROUP BY chunk_id
    ),
    doc_counts AS (
        SELECT d.filename, SUM(cc.times_cited) AS times_cited
        FROM chunk_counts cc
        JOIN knowledge_chunks kc ON kc.id = cc.chunk_id
        JOIN documents d ON d.id = kc.document_id
        GROUP BY d.filename
        ORDER BY times_cited DESC
        LIMIT 10
    )
    SELECT (SELECT total_documents FROM doc_count) AS total_documents,
           dc.filename AS document, dc.times_cited
    FROM doc_counts dc
"""


def document_citation_stats(scope: AdminScope) -> dict:
    """How many documents exist and which ones were cited most often across
    this tenant's conversations. `documents` and `knowledge_chunks` carry no
    tenant_id of their own (the knowledge base is shared across tenants),
    so the only tenant filter that makes sense is on which conversations'
    citations get counted -- applied above on `conversations.tenant_id`."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_DOCUMENT_CITATION_STATS_SQL, scope.as_params())
        columns = [d[0] for d in cur.description]
        rows = [list(r) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
    return {
        "intent": "document_citation_stats",
        "title": "Document count and most-cited documents",
        "columns": columns,
        "rows": _jsonify(rows),
    }


TEMPLATES = {
    "document_citation_stats": document_citation_stats,
}


def run_template(scope: AdminScope, template: str) -> dict:
    handler = TEMPLATES.get(template)
    if handler is None:
        raise AdminAnalyticsError(f"Unknown report template: {template}")
    return handler(scope)