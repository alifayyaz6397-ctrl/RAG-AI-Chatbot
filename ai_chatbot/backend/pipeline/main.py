from fastapi import FastAPI, UploadFile, File
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

class ChatRequest(BaseModel):
    question: str
    registration_number: str | None = None


@app.post("/api/chat")
async def chat(request: ChatRequest):

    student_ctx = None
    if request.registration_number:
        student_ctx = get_student_context(request.registration_number)

    chunks = retrieve_chunks(request.question)

    return StreamingResponse(
        generate_answer(request.question, chunks, student_ctx),
        media_type="text/plain"
    )


MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    # Check file size before doing anything else
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        return {"error": "File too large (max 20MB)"}
    await file.seek(0)

    # Save the uploaded file temporarily
    temp_path = f"temp_{file.filename}"
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Extract text (PDF only for now; MD handling added separately)
    if file.filename.lower().endswith(".pdf"):
        text = extract_text_from_pdf(temp_path)
    elif file.filename.lower().endswith(".md"):
        with open(temp_path, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        os.remove(temp_path)
        return {"error": "Only .pdf and .md files are supported"}

    os.remove(temp_path)

    # Insert into documents table, get its id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO documents (filename) VALUES (%s) RETURNING id",
        (file.filename,)
    )
    document_id = cur.fetchone()[0]
    conn.commit()

    # Chunk, embed, and store each chunk
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
async def preview_chunks(document_id: int):
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
async def delete_document(document_id: int):
    conn = get_connection()
    cur = conn.cursor()

    # Check the document actually exists first
    cur.execute("SELECT filename FROM documents WHERE id = %s", (document_id,))
    row = cur.fetchone()
    if row is None:
        cur.close()
        conn.close()
        return {"error": f"No document found with id {document_id}"}

    filename = row[0]

    # Delete chunks first, then the document itself
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