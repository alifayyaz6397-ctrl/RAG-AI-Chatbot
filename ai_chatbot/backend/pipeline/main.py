from fastapi import FastAPI, UploadFile, File, Depends
from pydantic import BaseModel
from retrieval import retrieve_chunks
from generation import generate_answer
from students import get_student_context
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import shutil
import os
from pdf_parser import extract_text_from_pdf
from chunking import chunk_text
from embedding import embed_text
from storage import get_connection
from Auth import router as auth_router, verify_token
from invigilator import generate_invigilator_answer
from retrieval import retrieve_exam_chunks

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Signup / login / /me routes now live in auth.py
app.include_router(auth_router)


class ChatRequest(BaseModel):
    question: str
    # registration_number removed -- identity now comes from the
    # verified JWT (user["linked_id"]), never from client input


@app.post("/api/chat")
async def chat(request: ChatRequest, user=Depends(verify_token)):

    student_ctx = None
    if user["role"] == "student":
        # linked_id is the student's internal student_id, taken from the
        # verified token -- not something the client can override
        student_ctx = get_student_context(user["linked_id"])

    chunks = retrieve_chunks(request.question)
    # print (chunks)      //print retreived chunks
    return StreamingResponse(
        generate_answer(request.question, chunks, user, student_ctx),
        media_type="text/plain"
    )


MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

@app.get("/api/documents")
async def list_documents(user=Depends(verify_token)):
    if user["role"] != "admin":
        return {"error": "Only admins can view the document list"}

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT d.id, d.filename, d.upload_date, COUNT(k.id) as chunk_count
        FROM documents d
        LEFT JOIN knowledge_chunks k ON k.document_id = d.id
        GROUP BY d.id, d.filename, d.upload_date
        ORDER BY d.upload_date DESC
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return {
        "documents": [
            {
                "id": r[0],
                "filename": r[1],
                "upload_date": r[2].isoformat() if r[2] else None,
                "chunk_count": r[3]
            }
            for r in rows
        ]
    }
@app.post("/api/documents/upload")

async def upload_document(file: UploadFile = File(...), document_type: str = "general"):
    # Check file size before doing anything else
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        return {"error": "File too large (max 20MB)"}
    await file.seek(0)

    # Save the uploaded file temporarily

    temp_path = f"temp_{file.filename}"
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    if file.filename.lower().endswith(".pdf"):
        text = extract_text_from_pdf(temp_path)
    elif file.filename.lower().endswith(".md"):
        with open(temp_path, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        os.remove(temp_path)
        return {"error": "Only .pdf and .md files are supported"}

    os.remove(temp_path)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO documents (filename, document_type) VALUES (%s, %s) RETURNING id",
        (file.filename, document_type)
    )
    document_id = cur.fetchone()[0]
    conn.commit()

    chunks = chunk_text(text)
    for i, chunk in enumerate(chunks):
        vector = embed_text(chunk)
        cur.execute(
            """
            INSERT INTO knowledge_chunks (source_document, chunk_index, content, embedding, document_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (file.filename, i, chunk, vector, document_id)
        )
    conn.commit()
    cur.close()
    conn.close()

    return {
        "document_id": document_id,
        "filename": file.filename,
        "chunks_created": len(chunks)
    }


@app.get("/api/documents/{document_id}/chunks")
async def preview_chunks(document_id: int, user=Depends(verify_token)):
    if user["role"] != "admin":
        return {"error": "Only admins can view chunk previews"}

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT chunk_index, content
        FROM knowledge_chunks
        WHERE document_id = %s
        ORDER BY chunk_index
        """,
        (document_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return {"document_id": document_id, "chunks": [], "message": "No chunks found for this document"}

    return {
        "document_id": document_id,
        "chunk_count": len(rows),
        "chunks": [{"chunk_index": r[0], "content": r[1]} for r in rows]
    }


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: int, user=Depends(verify_token)):
    if user["role"] != "admin":
        return {"error": "Only admins can delete documents"}

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT filename FROM documents WHERE id = %s", (document_id,))
    row = cur.fetchone()
    if row is None:
        cur.close()
        conn.close()
        return {"error": f"No document found with id {document_id}"}

    filename = row[0]

    cur.execute("DELETE FROM knowledge_chunks WHERE document_id = %s", (document_id,))
    chunks_deleted = cur.rowcount

    cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    conn.commit()

    cur.close()
    conn.close()

    return {
        "document_id": document_id,
        "filename": filename,
        "chunks_deleted": chunks_deleted,
        "status": "deleted"
    }
@app.get("/api/documents/citation-stats")
async def citation_stats(user=Depends(verify_token)):
    if user["role"] != "admin":
            return {"error": "Only admins can view the document stats"}
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(r"""SELECT
    d.id AS document_id,
    d.filename,
    COALESCE(stats.chunk_retrieval_count, 0) AS chunk_retrieval_count
FROM documents d
LEFT JOIN (
    SELECT
        k.document_id,
        COUNT(*) AS chunk_retrieval_count
    FROM conversations c
    CROSS JOIN LATERAL jsonb_array_elements(c.messages) AS msg
    CROSS JOIN LATERAL jsonb_array_elements_text(msg -> 'retrieved_chunk_id') AS chunk_id
    JOIN knowledge_chunks k
        ON chunk_id ~ '^\d+$' AND k.id = chunk_id::integer
    WHERE msg ->> 'role' = 'assistant'
    GROUP BY k.document_id
) stats ON stats.document_id = d.id
ORDER BY chunk_retrieval_count DESC;""")
    rows=cur.fetchall()
    cur.close()
    conn.close()
    return({
        "chunk_stats":[
            {
                "document_id":r[0],
                "document_name":r[1],
                "chunk_count":r[2]
            }
            for r in rows 
        ]
        }
    )

class ExamChatRequest(BaseModel):
    question: str


@app.post("/api/exam/chat")
async def exam_chat(request: ExamChatRequest,user=Depends(verify_token)):
    if user["role"] != "student":
        return {"error": "Exam mode is only available to students"}

    chunks = retrieve_exam_chunks(request.question)
    answer, escalate = generate_invigilator_answer(request.question, chunks, user)
    return {"answer": answer, "escalate": escalate}

# def fake_verify_token():
#     return {
#         "linked_id": "2026-SE-01",
#         "role": "student",
#         "tenant_id": "uet"
#     }
@app.get("/api/exam_mode")
async def exam_mode(user=Depends(verify_token)):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT EXISTS(
                SELECT 1
                FROM students s
                JOIN exams e ON e.department_id = s.department_id AND e.semester_id = s.semester_id
                WHERE s.id = %s
                  AND now() BETWEEN e.start_at AND e.end_at
            );
            """,
            (user["linked_id"],)
        )
        result = cur.fetchone()[0]
        cur.close()
        return {"exam_mode": result}
    finally:
        conn.close()