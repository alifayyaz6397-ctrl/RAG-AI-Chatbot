from storage import get_connection

def get_student_by_id(student_id: int) -> dict | None:
    """Fetch a single student's info by their student_id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT student_id, name, registration_number, course, semester, section FROM students WHERE student_id = %s",
        (student_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return None

    return {
        "student_id": row[0],
        "name": row[1],
        "registration_number": row[2],
        "course": row[3],
        "semester": row[4],
        "section": row[5]
    }

def get_student_by_registration(registration_number: str) -> dict | None:
    """Fetch a single student's info by their registration number."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT student_id, name, registration_number, course, semester, section FROM students WHERE registration_number = %s",
        (registration_number,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return None

    return {
        "student_id": row[0],
        "name": row[1],
        "registration_number": row[2],
        "course": row[3],
        "semester": row[4],
        "section": row[5]
    }

if __name__ == "__main__":
    result = get_student_by_id(1)
    print(result)