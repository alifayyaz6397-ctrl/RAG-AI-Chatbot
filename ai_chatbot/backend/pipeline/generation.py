"""
generation.py -- the general (non-exam) student chat answer path.

The draft is buffered rather than streamed straight through, because the
escalation decision depends on a self-check over the FINISHED answer, and the
client has to learn that decision from response headers -- which are sent
before the first byte of the body. build_answer() produces the finished answer
plus its metadata; stream_text() then hands the text to the client in slices so
the frontend's existing reader loop still renders it progressively.
"""

import os
import json
import uuid

from dotenv import load_dotenv
from google import genai

from storage import get_connection
import escalation

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# How much text each yield pushes to the client. The answer is complete before
# the first slice goes out -- see build_answer() for why.
STREAM_SLICE = 20


def create_conversation_id():
    return f"conv-{uuid.uuid4()}"


def build_answer(question: str, chunks: list[dict], user,
                 student_context: str | None = None, *,
                 session_id: str | None = None,
                 is_new_session: bool = False,
                 persist: bool = True) -> dict:
    """Produce the answer, score it, and persist everything.

    persist=False runs the identical path but writes nothing to the database.
    The evaluation harness uses it so a benchmark run does not fill
    `conversations` and `support_tickets` with synthetic traffic.

    session_id groups the turns of one chat together for the history sidebar;
    is_new_session additionally asks Gemini for a title for that session. Both
    are optional so the harness can call this with neither.
    """
    context = "\n\n".join(
        f"[Source: {c['source']}]\n{c['content']}"
        for c in chunks
    )

    student_line = f"\nStudent info: {student_context}\n" if student_context else ""

    prompt = f"""
Answer the question using only the context below.
If the context doesn't contain the answer, say so.
{student_line}
Context:
{context}

Question:
{question}

Answer:
"""

    response = client.models.generate_content_stream(model=MODEL, contents=prompt)
    draft = "".join(chunk.text for chunk in response if chunk.text)

    verdict = escalation.assess(question, draft, chunks)
    answer = draft + escalation.ESCALATION_NOTE if verdict["escalation_offered"] else draft

    conversation_id, ticket_id = None, None
    if persist:
        conversation_id = _save_conversation(question, answer, chunks, user,
                                             session_id=session_id,
                                             escalated=verdict["escalation_offered"])
        if verdict["escalation_offered"]:
            ticket_id = escalation.create_ticket(
                user, conversation_id,
                reason="low_confidence: " + ", ".join(verdict["reasons"]),
            )
        # Title the session from its opening exchange, once, on the first turn.
        if is_new_session and session_id:
            generate_session_title(question, draft, session_id)

    return {
        "answer": answer,
        "conversation_id": conversation_id,
        "ticket_id": ticket_id,
        **verdict,
    }


def stream_text(answer: str):
    """Hand the finished answer to the client in slices, so the frontend's
    existing reader loop still renders it progressively."""
    for i in range(0, len(answer), STREAM_SLICE):
        yield answer[i:i + STREAM_SLICE]


def _save_conversation(question, answer, chunks, user, session_id, escalated: bool) -> str:
    messages = [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer,
         "retrieved_chunk_id": [c["id"] for c in chunks if "id" in c]},
    ]

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO conversations (user_id, role, messages, tenant_id, mode, escalated, session_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (user["linked_id"], user["role"], json.dumps(messages),
             user["tenant_id"], "general", escalated, session_id)
        )
        conversation_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return conversation_id
    finally:
        conn.close()


def generate_session_title(question: str, answer: str, session_id: str) -> str:
    """One short label per chat session, generated from its first exchange and
    stored in session_titles for the history sidebar."""
    prompt = f"""Generate a short, descriptive title (max 6 words, no quotes, no punctuation at the end) for this conversation based on its first exchange.

Question: {question}
Answer: {answer[:300]}

Title:"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={"max_output_tokens": 200},
    )

    if response.text:
        title = response.text.strip().strip('"').strip("'")
    else:
        title = "New Chat"
    title = title[:60]  # hard safety cap on length

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO session_titles (title, session_id)
               VALUES (%s, %s)""",
            (title, session_id)
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return title
