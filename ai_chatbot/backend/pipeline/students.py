from storage import get_connection

def get_student_by_id(student_id: str) -> dict | None:
    """Fetch a single student's info by their id (e.g. '2025-CS-01')."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, email, department_id, enrollment_year, tenant_id FROM students WHERE id = %s",
        (student_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "email": row[2],
        "department_id": row[3],
        "enrollment_year": row[4],
        "tenant_id": row[5]
    }


def get_student_by_email(email: str) -> dict | None:
    """Fetch a single student's info by their email."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, email, department_id, enrollment_year, tenant_id FROM students WHERE email = %s",
        (email,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "email": row[2],
        "department_id": row[3],
        "enrollment_year": row[4],
        "tenant_id": row[5]
    }


# Caps on how much personal data goes into one prompt. A student with four
# years of history would otherwise push the retrieved chunks out of the
# context window, and the recent rows are the ones questions are actually
# about.
MAX_RESULTS = 15
MAX_UPCOMING = 10
MAX_CERTIFICATES = 15


def _fmt_date(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def get_student_results(student_id: str) -> list[dict]:
    """Graded exams for one student, newest first, with the exam they belong
    to and whether a certificate was issued."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT e.title, e.subject, e.date, r.score_percent, r.grade,
                   r.certificate_available, r.section_breakdown
            FROM results r
            JOIN exams e ON e.id = r.exam_id
            WHERE r.student_id = %s
            ORDER BY e.date DESC NULLS LAST
            LIMIT %s
            """,
            (student_id, MAX_RESULTS),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [
        {"exam": r[0], "subject": r[1], "date": r[2], "score_percent": r[3],
         "grade": r[4], "certificate_available": r[5], "section_breakdown": r[6]}
        for r in rows
    ]


def get_student_schedule(student_id: str) -> list[dict]:
    """Exams this student is enrolled in that have not finished yet, soonest
    first. Enrollment is the source of truth for "am I sitting this", so the
    join runs from enrollments rather than from the student's department."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT e.title, e.subject, e.date, e.start_at, e.end_at,
                   e.duration_minutes, e.status, en.enrolled_at
            FROM enrollments en
            JOIN exams e ON e.id = en.exam_id
            WHERE en.student_id = %s
              AND (e.end_at IS NULL OR e.end_at >= now())
            ORDER BY e.start_at ASC NULLS LAST, e.date ASC
            LIMIT %s
            """,
            (student_id, MAX_UPCOMING),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [
        {"exam": r[0], "subject": r[1], "date": r[2], "start_at": r[3],
         "end_at": r[4], "duration_minutes": r[5], "status": r[6],
         "enrolled_at": r[7]}
        for r in rows
    ]


def get_student_certificates(student_id: str) -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT e.title, c.issued_at, c.verification_code, c.grade,
                   c.score_percent, c.status, c.remark
            FROM certificates c
            JOIN exams e ON e.id = c.exam_id
            WHERE c.student_id = %s
            ORDER BY c.issued_at DESC NULLS LAST
            LIMIT %s
            """,
            (student_id, MAX_CERTIFICATES),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [
        {"exam": r[0], "issued_at": r[1], "verification_code": r[2],
         "grade": r[3], "score_percent": r[4], "status": r[5], "remark": r[6]}
        for r in rows
    ]


def get_student_context(student_id: str) -> str | None:
    """Everything the student chatbot is allowed to know about the caller,
    formatted for injection alongside the retrieved document chunks.

    The spec requires the student bot to answer about "their own results,
    enrollment status, certificate availability, upcoming exam schedule" -- so
    all four are assembled here rather than leaving the model to guess from a
    profile line, which is all this used to return.

    student_id always comes from the verified JWT (`user["linked_id"]`), never
    from anything the caller typed, so this can only ever describe the person
    asking. Nothing here is interpolated from user input.
    """
    student = get_student_by_id(student_id)
    if student is None:
        return None

    sections = [
        "Profile: "
        f"name {student['name']}, "
        f"id {student['id']}, "
        f"department {student['department_id']}, "
        f"enrollment year {student['enrollment_year']}"
    ]

    results = get_student_results(student_id)
    if results:
        lines = []
        for r in results:
            line = (f"- {r['exam']} ({r['subject']}, {_fmt_date(r['date'])}): "
                    f"{r['score_percent']}%, grade {r['grade']}")
            if r["section_breakdown"]:
                breakdown = ", ".join(f"{k} {v}" for k, v in r["section_breakdown"].items())
                line += f" [by section: {breakdown}]"
            line += (" -- certificate available"
                     if r["certificate_available"] else " -- no certificate issued")
            lines.append(line)
        sections.append("Results (most recent first):\n" + "\n".join(lines))
    else:
        sections.append("Results: no graded results recorded yet.")

    schedule = get_student_schedule(student_id)
    if schedule:
        lines = [
            f"- {s['exam']} ({s['subject']}): {_fmt_date(s['date'])}"
            + (f" at {_fmt_date(s['start_at'])}" if s["start_at"] else "")
            + (f", {s['duration_minutes']} minutes" if s["duration_minutes"] else "")
            + f", status {s['status']}"
            for s in schedule
        ]
        sections.append("Upcoming exams they are enrolled in:\n" + "\n".join(lines))
    else:
        sections.append("Upcoming exams: none currently scheduled.")

    certificates = get_student_certificates(student_id)
    if certificates:
        lines = [
            f"- {c['exam']}: issued {_fmt_date(c['issued_at'])}, "
            f"grade {c['grade']}, status {c['status']}"
            + (f", {c['remark']}" if c["remark"] else "")
            + f", verification code {c['verification_code']}"
            for c in certificates
        ]
        sections.append("Certificates:\n" + "\n".join(lines))
    else:
        sections.append("Certificates: none issued yet.")

    return "\n\n".join(sections)


if __name__ == "__main__":
    print(get_student_context("2025-CS-01"))

def get_active_exam(student_id: str) -> dict | None:
    """The exam this student is sitting right now, or None.

    Mirrors the join /api/exam_mode uses to decide whether to lock the chat
    into invigilator mode -- department + semester, with now() inside the
    exam window -- so the two cannot disagree about which exam is live.

    minutes_remaining is computed in Postgres rather than in Python so it is
    measured against the same clock the exam window is stored in.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT e.id, e.title, e.subject, e.start_at, e.end_at,
                   e.duration_minutes,
                   GREATEST(0, CEIL(EXTRACT(EPOCH FROM (e.end_at - now())) / 60.0))
            FROM students s
            JOIN exams e
              ON e.department_id = s.department_id
             AND e.semester_id  = s.semester_id
            WHERE s.id = %s
              AND now()::timestamp BETWEEN e.start_at AND e.end_at
            ORDER BY e.end_at ASC
            LIMIT 1
            """,
            (student_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if row is None:
        return None

    return {
        "id": row[0], "title": row[1], "subject": row[2],
        "start_at": row[3], "end_at": row[4],
        "duration_minutes": row[5],
        "minutes_remaining": int(row[6]) if row[6] is not None else None,
    }
