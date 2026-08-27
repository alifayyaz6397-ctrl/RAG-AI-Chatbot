from fastapi import (FastAPI, UploadFile, File, Depends, HTTPException, Query,
                     BackgroundTasks)
from google.genai import types
from pydantic import BaseModel
from retrieval import retrieve_chunks
from generation import build_answer, stream_text
from students import get_student_context
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from conversations import store_rating,suggesation_qns
import os
import tempfile
from pdf_parser import extract_text_from_pdf
from chunking import chunk_text
from embedding import embed_texts
from storage import get_connection
from Auth import router as auth_router, verify_token
from invigilator import generate_invigilator_answer
from retrieval import retrieve_exam_chunks
import instructor
from analytics import AnalyticsError, Scope, list_owned_exams
import conversations as conversation_store
import feedback

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Custom response headers are invisible to browser JS unless they are
    # explicitly exposed -- without this the frontend cannot read the
    # escalation flag even though it is being sent.
    expose_headers=[
        "X-Escalation-Offered",
        "X-Confidence",
        "X-Conversation-Id",
        "X-Ticket-Id",
    ],
)

# Signup / login / /me routes now live in auth.py
app.include_router(auth_router)

class ChatRequest(BaseModel):
    question: str
    session_id: str
    isNewSession:bool
    # registration_number removed -- identity now comes from the
    # verified JWT (user["linked_id"]), never from client input

ADMIN_ROUTER_TOOLS = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="search_knowledge_base",
            description=(
                "Search course materials and uploaded documents for conceptual, "
                "factual, or how-to questions -- definitions, explanations, "
                "'what is X', 'how does X work', course content lookups. Use "
                "this for anything that isn't about counting, aggregating, or "
                "looking up records in the platform's own data."
            ),
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        types.FunctionDeclaration(
            name="run_analytics",
            description=(
                "Answer questions about the platform's own stored data -- "
                "student/instructor/department counts, exam results, pass "
                "rates, enrollments, certificates, support tickets, "
                "escalations, or conversation/citation stats. Use this for "
                "anything that needs a number or record pulled from the "
                "database rather than explained from course material."
            ),
            parameters={
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        ),
    ])
]


def _route_admin_question(question: str) -> str:
    """Asks Gemini which lane an admin's question belongs in. Defaults to
    'search_knowledge_base' whenever the model doesn't clearly call
    run_analytics -- small talk, an unclear question, or a failed call all
    fall back to RAG, since RAG answering plainly ("that's not in the
    provided context") is a safe failure mode and silently routing into
    analytics on a weak signal is not. This only decides which existing
    pipeline runs; it doesn't touch the database or the knowledge base
    itself, and everything downstream (Scope/AdminScope, validate_sql, the
    template allowlist) still applies exactly as before."""
    try:
        response = instructor.client.models.generate_content(
            model=instructor.MODEL,
            contents=question,
            config=types.GenerateContentConfig(tools=ADMIN_ROUTER_TOOLS),
        )
        part = response.candidates[0].content.parts[0]
        function_call = getattr(part, "function_call", None)
        if function_call and function_call.name == "run_analytics":
            return "run_analytics"
    except Exception:
        pass
    return "search_knowledge_base"


# --- replace the existing /api/chat route with this ---

@app.post("/api/chat")
async def chat(request: ChatRequest, user=Depends(verify_token)):
    student_ctx = None
    if user["role"] == "student":
        # linked_id is the student's internal student_id, taken from the
        # verified token -- not something the client can override
        student_ctx = get_student_context(user["linked_id"])

    if user["role"] == "admin":
        route = _route_admin_question(request.question)
        if route == "run_analytics":
            try:
                return instructor.answer_admin_question(request.question, request.session_id, request.isNewSession,user)
            except AnalyticsError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            except instructor.ModelUnavailable:
                raise HTTPException(
                    status_code=503,
                    detail="The analytics assistant is busy right now. Please try again in a moment.",
                )
        # else: fall through to RAG below, same as every other role

    chunks = retrieve_chunks(request.question, tenant_id=user["tenant_id"])
    result = build_answer(request.question, chunks, user, student_ctx,
                          session_id=request.session_id,
                          is_new_session=request.isNewSession)

    # The escalation decision travels in headers, never in the body. The
    # frontend reads this response as a raw text stream, so anything merged
    # into the body would render as visible text in the student's chat.
    headers = {
        "X-Escalation-Offered": str(result["escalation_offered"]).lower(),
        "X-Confidence": str(result["top_similarity"]),
        "X-Conversation-Id": result["conversation_id"],
    }
    if result["ticket_id"]:
        headers["X-Ticket-Id"] = result["ticket_id"]

    return StreamingResponse(
        stream_text(result["answer"]),
        media_type="text/plain",
        headers=headers,
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
def _ingest_document(document_id: int, filename: str, text: str, tenant_id: str):
    """Chunk, embed and store one document. Runs in a background task, so
    nothing here may assume a live request -- it owns its own connection and
    records its own outcome in documents.ingest_status.

    Embedding is batched (see embedding.embed_texts): a 100-page PDF is a few
    round trips rather than a few hundred, which is what makes the 5-minute
    ingestion NFR reachable.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE documents SET ingest_status = 'running' WHERE id = %s",
                    (document_id,))
        conn.commit()

        chunks = chunk_text(text)
        cur.execute("UPDATE documents SET chunk_total = %s WHERE id = %s",
                    (len(chunks), document_id))
        conn.commit()

        vectors = embed_texts(chunks)
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            cur.execute(
                """
                INSERT INTO knowledge_chunks
                    (source_document, chunk_index, content, embedding, document_id, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (filename, i, chunk, vector, document_id, tenant_id)
            )
        cur.execute("UPDATE documents SET ingest_status = 'ready', ingest_error = NULL WHERE id = %s",
                    (document_id,))
        conn.commit()
        cur.close()
    except Exception as exc:
        conn.rollback()
        cur = conn.cursor()
        # Partial chunks from a failed run would be retrieved as if they were a
        # whole document, so the document is emptied before it is marked failed.
        cur.execute("DELETE FROM knowledge_chunks WHERE document_id = %s", (document_id,))
        cur.execute(
            "UPDATE documents SET ingest_status = 'failed', ingest_error = %s WHERE id = %s",
            (str(exc)[:2000], document_id),
        )
        conn.commit()
        cur.close()
        print(f"[INGEST FAILED] document {document_id}: {exc}")
    finally:
        conn.close()


@app.post("/api/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: str = "general",
    user=Depends(verify_token),
):
    """Parses and registers the document synchronously, then hands chunking and
    embedding to a background task. The knowledge base is also the prompt
    injection surface, so this is admin-only -- it used to have no auth at all.
    """
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can upload documents")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20MB)")

    # os.path.basename strips any directory component: a filename of
    # "../../main.py" would otherwise be written (and deleted) outside the
    # working directory. tempfile keeps concurrent uploads of the same
    # filename from overwriting each other.
    safe_name = os.path.basename(file.filename or "")
    lowered = safe_name.lower()
    if not (lowered.endswith(".pdf") or lowered.endswith(".md")):
        raise HTTPException(status_code=400, detail="Only .pdf and .md files are supported")

    fd, temp_path = tempfile.mkstemp(suffix=safe_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contents)
        if lowered.endswith(".pdf"):
            text = extract_text_from_pdf(temp_path)
        else:
            text = contents.decode("utf-8", errors="replace")
    finally:
        os.remove(temp_path)

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="No extractable text found (a scanned PDF needs OCR before upload)",
        )

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO documents (filename, document_type, tenant_id, ingest_status)
               VALUES (%s, %s, %s, 'pending') RETURNING id""",
            (safe_name, document_type, user["tenant_id"])
        )
        document_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
    finally:
        conn.close()

    background_tasks.add_task(_ingest_document, document_id, safe_name, text,
                              user["tenant_id"])

    return {
        "document_id": document_id,
        "filename": safe_name,
        "ingest_status": "pending",
        "message": "Upload accepted. Chunking and embedding are running in the background.",
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
@app.get("/api/exam/{exam_id}/info")
async def exam_info(exam_id: str, user=Depends(verify_token)):
    if user["role"] not in ("instructor", "admin"):
        raise HTTPException(status_code=403,
                            detail="Only instructors and admins can view exam details")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id ,title,subject,date,duration_minutes,start_at,end_at,department_id,semester_id,status
        FROM exams
        WHERE id = %s
        """,
        (exam_id,)
    )
    row = cur.fetchall()
    rows=row[0]
    cur.close()
    conn.close()
    if not rows:
        return {}

    return {"exam":{
        "id": rows[0],
        "title": rows[1],
        "subject": rows[2],
        "date": rows[3],
        "duration": rows[4],
        "start_at": rows[5],
        "end_at": rows[6],
        "department_id": rows[7],
        "semester_id": rows[8],
        "status": rows[9]
    }};


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
    session_id:str


@app.post("/api/exam/chat")
async def exam_chat(request: ExamChatRequest,user=Depends(verify_token)):
    if user["role"] != "student":
        return {"error": "Exam mode is only available to students"}

    chunks = retrieve_exam_chunks(request.question, tenant_id=user["tenant_id"])
    # Keyword args deliberately: the positional order here was question,
    # session_id, chunks, user against a signature of question, chunks, user,
    # session_id, so every argument landed in the wrong parameter.
    answer = generate_invigilator_answer(
        request.question, chunks, user, session_id=request.session_id,
    )
    return StreamingResponse(answer, media_type="text/plain")


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
                  AND now() ::timestamp BETWEEN e.start_at AND e.end_at);
				  
    """,
    (user["linked_id"],)
)
        result = cur.fetchone()[0]
        cur.close()
        return {"exam_mode": result}
    finally:
        conn.close()
        
# ---------------------------------------------------------
# Instructor analytics
# ---------------------------------------------------------

class InstructorChatRequest(BaseModel):
    question: str
    session_id: str
    isNewSession:bool


@app.post("/api/instructor/chat")
async def instructor_chat(request: InstructorChatRequest, user=Depends(verify_token)):
    """Not a streamed response, unlike the student and exam chats: the useful
    part of an analytics answer is the result table, and a table is structured
    data rather than something to trickle out a token at a time."""
    try:
        return instructor.answer_instructor_question(request.question, request.session_id,request.isNewSession,user)
    except AnalyticsError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except instructor.ModelUnavailable:
        # The question was never classified, so there is no report to fall back
        # to -- unlike a failure in the report writer, which degrades to the
        # raw numbers instead of failing.
        raise HTTPException(
            status_code=503,
            detail="The analytics assistant is busy right now. Please try again in a moment.",
        )


@app.get("/api/instructor/exams")
async def instructor_exams(user=Depends(verify_token)):
    """The exams this instructor owns -- lets the UI show what is actually
    reportable instead of making them guess at exam names."""
    try:
        return {"exams": list_owned_exams(Scope(user))}
    except AnalyticsError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


# ---------------------------------------------------------
# Conversation history
# ---------------------------------------------------------

@app.get("/api/conversations")
async def list_my_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(conversation_store.DEFAULT_PAGE_SIZE, ge=1, le=conversation_store.MAX_PAGE_SIZE),
    mode: str | None = Query(None, description="general | exam | instructor"),
    user=Depends(verify_token),
):
    convo= conversation_store.list_conversations(user, page=page, page_size=page_size, mode=mode)
    return {"session":convo}

# Declared before /api/conversations/{conversation_id} would otherwise be a
# concern, but the admin route sits under /api/admin/ so there is no clash.
@app.get("/api/admin/conversations")
async def list_all_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(conversation_store.DEFAULT_PAGE_SIZE, ge=1, le=conversation_store.MAX_PAGE_SIZE),
    user_id: str | None = Query(None),
    role: str | None = Query(None, description="student | instructor | admin"),
    mode: str | None = Query(None, description="general | exam | instructor"),
    escalated: bool | None = Query(None),
    user=Depends(verify_token),
):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view all conversations")

    return conversation_store.list_all_conversations(
        user, page=page, page_size=page_size,
        user_id=user_id, role=role, mode=mode, escalated=escalated,
    )


@app.get("/api/conversations/{session_id}")
async def get_conversation(session_id, user=Depends(verify_token)):
    conversation = conversation_store.get_conversation(user, session_id)
    # "not yours" and "does not exist" deliberately collapse into one 404 so
    # this cannot be used to enumerate other users' conversation ids.
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"chat":conversation}


@app.get("/me")
def get_my_identity(user=Depends(verify_token)):
    return {"role": user["role"], "linked_id": user["linked_id"], "tenant_id": user["tenant_id"], "username" : user["username"]}

class getRating(BaseModel):
    rating: str

@app.post("/api/conversations/{conv_id}/rate")
def chatRating(conv_id: str, rating: getRating, user=Depends(verify_token)):
    store_rating(rating.rating, conv_id)
    return {"status": "ok"}

@app.get("/api/suggestion_qns/{role}")
def suggestions(role: str, user=Depends(verify_token)):
    """`role` stays in the path so the existing frontend call keeps working,
    but it is ignored -- the suggestion set is chosen by the verified token.
    Otherwise any student could request the admin prompt set by editing the
    URL, which leaks what the admin console can be asked to do."""
    return {"suggestions": suggesation_qns(user["role"])}

# ---------------------------------------------------------
# Message feedback
#
# Restored: these two routes and the `import feedback` above were dropped by
# the "keep incoming version for conflicted files" merge, which left
# feedback.py in the tree with nothing importing it. The thumbs-up/down loop
# and the admin review queue are week-6 deliverables.
# ---------------------------------------------------------

class FeedbackRequest(BaseModel):
    message_id: str          # "<conversation_id>:<message_index>", e.g. "conv-140:1"
    rating: str              # "up" | "down"
    comment: str | None = None


@app.post("/api/feedback")
async def submit_feedback(request: FeedbackRequest, user=Depends(verify_token)):
    try:
        return feedback.submit_feedback(
            user, request.message_id, request.rating, request.comment
        )
    except feedback.FeedbackError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/admin/feedback")
async def feedback_review_queue(
    rating: str = Query("down", description="down | up"),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(verify_token),
):
    """Admin review queue: low-rated answers rolled up by cited chunk and by
    source document, so a weak KB doc is visible rather than inferred."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view the feedback queue")
    try:
        return feedback.review_queue(user, rating=rating, limit=limit)
    except feedback.FeedbackError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
