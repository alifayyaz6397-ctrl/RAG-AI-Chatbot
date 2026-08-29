"""
analytics.py -- the query-template registry behind /api/instructor/chat.

Deliberately NOT free-form SQL. Gemini's only job is to pick one intent from a
fixed list and pull a few parameters out of the question. Every statement below
is hand-written, fully parameterised, and hard-scoped to the caller's
tenant_id + owner_instructor_id. The worst a prompt injection can achieve is
picking the wrong template -- it can never reach another instructor's exams,
another tenant's data, or anything outside these four queries.

"Sections" here means the keys inside results.section_breakdown
(MCQ / ShortAnswer / LongAnswer), which is the only notion of section the
schema actually has.

Pass/fail uses the stored `grade` column rather than a threshold invented here.
In the current data grade 'F' is exactly score_percent < 40, but the grade is
the authoritative record, so we count `grade <> 'F'` as a pass.
"""

import re

from storage import get_connection

INTENTS = ("average_score", "section_performance", "pass_rate", "attempt_count")

# Instructors are the only role allowed through this module.
ALLOWED_ROLES = ("instructor",)


class AnalyticsError(Exception):
    """Raised for problems we want reported to the instructor verbatim
    (unknown exam name, no exams owned, etc) rather than fed to the LLM."""


class Scope:
    """Everything that limits what this caller may see. Built from the verified
    JWT only -- never from anything the client or the model produced."""

    def __init__(self, user):
        if user.get("role") not in ALLOWED_ROLES:
            raise AnalyticsError("Analytics are only available to instructors.")
        self.tenant_id = user["tenant_id"]
        self.instructor_id = user["linked_id"]

    def as_params(self):
        return {"tenant_id": self.tenant_id, "instructor_id": self.instructor_id}


# ---------------------------------------------------------------------------
# Exam resolution
# ---------------------------------------------------------------------------

# Every exam lookup runs through here, so the tenant + owner filter is applied
# once and cannot be forgotten by an individual template.
_OWNED_EXAMS_SQL = """
    SELECT id, title, subject, date, status
    FROM exams
    WHERE tenant_id = %(tenant_id)s
      AND owner_instructor_id = %(instructor_id)s
"""


def list_owned_exams(scope: Scope) -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_OWNED_EXAMS_SQL + " ORDER BY date DESC", scope.as_params())
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [
        {"id": r[0], "title": r[1], "subject": r[2],
         "date": r[3].isoformat() if r[3] else None, "status": r[4]}
        for r in rows
    ]


def _tokens(text: str | None) -> set[str]:
    """Lowercased alphanumeric words. Punctuation is dropped so that
    "Data Structures final" still matches "Data Structures - Final"."""
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def resolve_exams(scope: Scope, exam_query: str | None) -> list[dict]:
    """Turn a free-text exam name into concrete exam ids the caller owns.

    Matching is token-based rather than substring-based: instructors type
    "the Data Structures final", not "Data Structures - Final", and the
    classifier echoes their phrasing back rather than a canonical title.

    No match is an error rather than a silent fall-back to "all exams" -- a
    report that quietly answers about the wrong exams is worse than one that
    says it couldn't find the exam.
    """
    owned = list_owned_exams(scope)
    if not owned:
        raise AnalyticsError(
            "You don't own any exams yet, so there's nothing to report on."
        )

    if not exam_query:
        return owned

    needle = exam_query.strip().lower()
    exact = [e for e in owned if e["id"].lower() == needle or e["title"].lower() == needle]
    if exact:
        return exact

    # Every word the instructor used must appear somewhere in the exam's
    # title/subject/id. "quiz 1" narrows to one exam; "data structures"
    # legitimately matches three, and all three get reported.
    wanted = _tokens(needle)
    matches = [
        e for e in owned
        if wanted and wanted <= (_tokens(e["title"]) | _tokens(e["subject"]) | _tokens(e["id"]))
    ]
    if not matches:
        # Last resort: a raw substring, which catches partial words like
        # "struct" that tokenising cannot.
        matches = [
            e for e in owned
            if needle in e["title"].lower()
            or needle in (e["subject"] or "").lower()
            or needle in e["id"].lower()
        ]
    if not matches:
        titles = ", ".join(e["title"] for e in owned[:10])
        raise AnalyticsError(
            f"I couldn't find an exam of yours matching \"{exam_query}\". "
            f"Your exams include: {titles}."
        )
    return matches


def _base_params(scope: Scope, exams: list[dict], params: dict) -> dict:
    return {
        **scope.as_params(),
        "exam_ids": [e["id"] for e in exams],
        "start_date": params.get("start_date"),
        "end_date": params.get("end_date"),
    }


# Shared filter fragment. exam_ids is always a concrete list produced by
# resolve_exams(), so the tenant/owner filter has already been applied once
# before this even runs -- it is repeated here as defence in depth.
_SCOPE_FILTER = """
    WHERE e.tenant_id = %(tenant_id)s
      AND e.owner_instructor_id = %(instructor_id)s
      AND e.id = ANY(%(exam_ids)s)
      AND (%(start_date)s::date IS NULL OR e.date >= %(start_date)s::date)
      AND (%(end_date)s::date   IS NULL OR e.date <= %(end_date)s::date)
"""


def _run(sql: str, params: dict) -> tuple[list[str], list[list]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        columns = [d[0] for d in cur.description]
        rows = [list(r) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
    return columns, rows


def _jsonify(rows: list[list]) -> list[list]:
    """Decimal/date -> float/str so the rows survive json.dumps on the way to
    the report writer and out to the client."""
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
# The four templates
# ---------------------------------------------------------------------------

def average_score(scope: Scope, params: dict) -> dict:
    exams = resolve_exams(scope, params.get("exam"))
    sql = f"""
        SELECT e.title       AS exam,
               e.subject     AS subject,
               e.date        AS exam_date,
               COUNT(r.*)                     AS students_scored,
               ROUND(AVG(r.score_percent), 2) AS average_score_percent,
               MIN(r.score_percent)           AS lowest_score_percent,
               MAX(r.score_percent)           AS highest_score_percent
        FROM exams e
        JOIN results r ON r.exam_id = e.id
        {_SCOPE_FILTER}
        GROUP BY e.id, e.title, e.subject, e.date
        ORDER BY e.date DESC
    """
    columns, rows = _run(sql, _base_params(scope, exams, params))
    return {
        "intent": "average_score",
        "title": "Average score per exam",
        "columns": columns,
        "rows": _jsonify(rows),
    }


def section_performance(scope: Scope, params: dict) -> dict:
    exams = resolve_exams(scope, params.get("exam"))
    sql_params = _base_params(scope, exams, params)
    section = params.get("section")
    sql_params["section"] = f"%{section.strip()}%" if section else None

    sql = f"""
        SELECT kv.key                             AS section,
               COUNT(*)                           AS scores_counted,
               ROUND(AVG((kv.value)::numeric), 2) AS average_score_percent,
               MIN((kv.value)::numeric)           AS lowest_score_percent,
               MAX((kv.value)::numeric)           AS highest_score_percent
        FROM exams e
        JOIN results r ON r.exam_id = e.id
        CROSS JOIN LATERAL jsonb_each(r.section_breakdown) kv
        {_SCOPE_FILTER}
          AND jsonb_typeof(kv.value) = 'number'
          AND (%(section)s::text IS NULL OR kv.key ILIKE %(section)s)
        GROUP BY kv.key
        ORDER BY average_score_percent ASC
    """
    columns, rows = _run(sql, sql_params)
    return {
        "intent": "section_performance",
        "title": "Average score per section (weakest first)",
        "columns": columns,
        "rows": _jsonify(rows),
        "exams_covered": [e["title"] for e in exams],
    }


def pass_rate(scope: Scope, params: dict) -> dict:
    exams = resolve_exams(scope, params.get("exam"))
    sql = f"""
        SELECT e.title AS exam,
               e.date   AS exam_date,
               COUNT(r.*)                                 AS students_scored,
               COUNT(*) FILTER (WHERE r.grade <> 'F')     AS students_passed,
               ROUND(100.0 * COUNT(*) FILTER (WHERE r.grade <> 'F')
                     / NULLIF(COUNT(r.*), 0), 2)          AS pass_rate_percent
        FROM exams e
        JOIN results r ON r.exam_id = e.id
        {_SCOPE_FILTER}
        GROUP BY e.id, e.title, e.date
        ORDER BY e.date DESC
    """
    columns, rows = _run(sql, _base_params(scope, exams, params))
    return {
        "intent": "pass_rate",
        "title": "Pass rate per exam (a pass is any grade other than F)",
        "columns": columns,
        "rows": _jsonify(rows),
    }


def attempt_count(scope: Scope, params: dict) -> dict:
    exams = resolve_exams(scope, params.get("exam"))
    # enrollments and results are both one-to-many against exams, so the two
    # LEFT JOINs multiply rows -- COUNT(DISTINCT ...) is what keeps the
    # numbers honest here.
    sql = f"""
        SELECT e.title  AS exam,
               e.date   AS exam_date,
               e.status AS exam_status,
               COUNT(DISTINCT en.student_id) AS students_enrolled,
               COUNT(DISTINCT r.student_id)  AS students_attempted,
               ROUND(100.0 * COUNT(DISTINCT r.student_id)
                     / NULLIF(COUNT(DISTINCT en.student_id), 0), 2)
                                             AS participation_percent
        FROM exams e
        LEFT JOIN enrollments en ON en.exam_id = e.id
        LEFT JOIN results     r  ON r.exam_id  = e.id
        {_SCOPE_FILTER}
        GROUP BY e.id, e.title, e.date, e.status
        ORDER BY e.date DESC
    """
    columns, rows = _run(sql, _base_params(scope, exams, params))
    return {
        "intent": "attempt_count",
        "title": "Enrolled vs attempted per exam",
        "columns": columns,
        "rows": _jsonify(rows),
    }


REGISTRY = {
    "average_score": average_score,
    "section_performance": section_performance,
    "pass_rate": pass_rate,
    "attempt_count": attempt_count,
}


def run_intent(scope: Scope, intent: str, params: dict) -> dict:
    handler = REGISTRY.get(intent)
    if handler is None:
        raise AnalyticsError(f"Unknown report type: {intent}")
    return handler(scope, params or {})
