import os
from dotenv import load_dotenv
from google import genai
from storage import get_connection
import json

import escalation

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# How much text each yield pushes to the client. The answer is complete before
# the first slice goes out -- see build_answer() for why.
STREAM_SLICE = 20


def build_answer(question: str, chunks: list[dict], user,
                 student_context: str | None = None, persist: bool = True) -> dict:
    """Produce the answer, score it, and persist everything.

    persist=False runs the identical path but writes nothing to the database.
    The evaluation harness uses it so a benchmark run does not fill
    `conversations` and `support_tickets` with synthetic traffic.

    The draft is buffered rather than streamed straight through, because the
    escalation decision depends on a self-check over the FINISHED answer, and
    the client has to learn that decision from response headers -- which are
    sent before the first byte of the body. This is the same buffer-then-emit
    shape invigilator.generate_invigilator_answer() already uses, and it is
    also what keeps the escalation metadata out of the visible text: the flag
    travels in headers, never concatenated into the answer.
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
                                             escalated=verdict["escalation_offered"])
        if verdict["escalation_offered"]:
            ticket_id = escalation.create_ticket(
                user, conversation_id,
                reason="low_confidence: " + ", ".join(verdict["reasons"]),
            )

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


def _save_conversation(question, answer, chunks, user, escalated: bool) -> str:
    messages = [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer,
         "retrieved_chunk_id": [c["id"] for c in chunks if "id" in c]},
    ]

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO conversations (user_id, role, messages, tenant_id, mode, escalated)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (user["linked_id"], user["role"], json.dumps(messages),
             user["tenant_id"], "general", escalated)
        )
        conversation_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return conversation_id
    finally:
        conn.close()
