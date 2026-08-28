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


def get_student_context(student_id: str) -> str | None:
    """
    Fetch a student and format their info as a short context string,
    ready to inject into a prompt alongside document chunks.
    """
    student = get_student_by_id(student_id)
    if student is None:
        return None

    return (
        f"Student: {student['name']}, "
        f"ID: {student['id']}, "
        f"Department: {student['department_id']}, "
        f"Enrollment Year: {student['enrollment_year']}"
    )


if __name__ == "__main__":
    print(get_student_context("2025-CS-01"))