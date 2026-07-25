"""
auth.py — Signup, login, and JWT verification.

Matches the ACTUAL current schema (confirmed via information_schema query):
  - students.id, instructors.id, admins.id are all VARCHAR (e.g. "2025-CS-01")
  - user_info.student_id / instructor_id / admin_id are VARCHAR FKs matching those
  - every identity table has tenant_id

Reuses the existing DB connection (storage.get_connection) and the
existing student lookup (students.get_student_by_id) rather than
duplicating either.

Identity flow:
  1. Student signs up with their student id (e.g. "2025-CS-01") or email
     -> must already exist in `students` table
  2. Login checks username/password in `user_info` -> issues a JWT
  3. Every protected route verifies the JWT and reads role/linked_id/tenant_id
     from it directly -- never from client input
"""

import os
import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from storage import get_connection
from students import get_student_by_id

router = APIRouter()
security = HTTPBearer()

SECRET_KEY = os.environ["JWT_SECRET"]  # must be set -- no silent weak default
ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 8


# ---------------------------------------------------------
# Request/response models
# ---------------------------------------------------------

class SignupRequest(BaseModel):
    student_id: str      # e.g. "2025-CS-01" -- must already exist in `students`
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    role: str


# ---------------------------------------------------------
# Signup (student self-serve only)
# ---------------------------------------------------------

@router.post("/signup", response_model=TokenResponse)
def signup(req: SignupRequest):
    # 1. Confirm this student_id matches a real student record
    student = get_student_by_id(req.student_id)
    if student is None:
        raise HTTPException(status_code=400, detail="No matching student record found")

    tenant_id = student["tenant_id"]

    conn = get_connection()
    cur = conn.cursor()

    # 2. Confirm no account already exists for this student
    cur.execute("SELECT id FROM user_info WHERE student_id = %s", (req.student_id,))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="An account already exists for this student")

    # 3. Confirm username isn't taken
    cur.execute("SELECT id FROM user_info WHERE username = %s", (req.username,))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Username already taken")

    # 4. Hash password and insert
    password_hash = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    cur.execute(
        """INSERT INTO user_info (username, password_hash, role, student_id, tenant_id)
           VALUES (%s, %s, 'student', %s, %s)""",
        (req.username, password_hash, req.student_id, tenant_id)
    )
    conn.commit()
    cur.close()
    conn.close()

    token = create_token(role="student", linked_id=req.student_id, tenant_id=tenant_id)
    return TokenResponse(access_token=token, role="student")


# ---------------------------------------------------------
# Login (all roles)
# ---------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """SELECT password_hash, role, student_id, instructor_id, admin_id, tenant_id
           FROM user_info WHERE username = %s""",
        (req.username,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    password_hash, role, student_id, instructor_id, admin_id, tenant_id = row

    if not bcrypt.checkpw(req.password.encode(), password_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    linked_id = {"student": student_id, "instructor": instructor_id, "admin": admin_id}[role]

    token = create_token(role=role, linked_id=linked_id, tenant_id=tenant_id)
    return TokenResponse(access_token=token, role=role)


# ---------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------

def create_token(role: str, linked_id: str, tenant_id: str) -> str:
    payload = {
        "role": role,
        "linked_id": linked_id,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------
# Example protected route
# ---------------------------------------------------------

@router.get("/me")
def get_my_identity(user=Depends(verify_token)):
    return {"role": user["role"], "linked_id": user["linked_id"], "tenant_id": user["tenant_id"]}