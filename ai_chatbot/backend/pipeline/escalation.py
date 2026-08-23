"""
escalation.py -- confidence scoring and hand-off for the general student chat.

Two independent signals decide whether the bot should admit it may be out of
its depth and offer a human:

  1. Retrieval confidence -- cosine similarity of the best-matching chunk.
     pgvector's `<=>` returns cosine DISTANCE, so similarity is 1 - distance.
     Measured against this knowledge base, off-topic questions floor at about
     0.50 similarity while genuine hits sit at 0.73+, so the 0.65 default
     threshold sits in the empty band between the two. It is the same cut-off
     `retrieval.MAX_DISTANCE` (0.35 distance) already uses for exam chunks.

  2. A Gemini self-check -- does the drafted answer actually follow from the
     retrieved context? This catches the case retrieval confidence cannot:
     chunks that look topically close but do not contain the answer, which is
     exactly where the model is tempted to fill the gap itself.

Either signal firing offers the escalation. They are deliberately OR-ed, not
AND-ed: the cost of an unnecessary offer is a small annoyance, the cost of a
missed one is a confidently wrong answer to a student.
"""

import os

from dotenv import load_dotenv

from storage import get_connection
import llm

load_dotenv()

SIMILARITY_THRESHOLD = float(os.environ.get("ESCALATION_SIMILARITY_THRESHOLD", "0.65"))

ESCALATION_NOTE = (
    "\n\nI'm not confident this fully answers your question. "
    "If you'd like, a member of staff can follow up with you."
)

SELF_CHECK_PROMPT = """You are a strict grader, not a chatbot.

Decide whether the ANSWER is fully supported by the CONTEXT.

Reply UNSUPPORTED if the answer states any fact that is not present in the
context, fills a gap with general knowledge, or answers a question the context
simply does not cover.

Reply SUPPORTED if every claim in the answer traces back to the context, OR if
the answer honestly says it does not know / that the context does not cover the
question. An honest refusal is always SUPPORTED -- it invents nothing.

CONTEXT:
{context}

QUESTION: {question}

ANSWER: {answer}

Respond with exactly one word: SUPPORTED or UNSUPPORTED.
"""


def retrieval_confidence(chunks: list[dict]) -> dict:
    """Cosine similarity of the retrieved set. The decision uses the best
    chunk, since one strongly-matching chunk is enough to answer from; the
    mean is reported alongside it for diagnostics."""
    if not chunks:
        return {"top_similarity": 0.0, "mean_similarity": 0.0, "chunks": 0}

    similarities = [1.0 - float(c["distance"]) for c in chunks if c.get("distance") is not None]
    if not similarities:
        return {"top_similarity": 0.0, "mean_similarity": 0.0, "chunks": len(chunks)}

    return {
        "top_similarity": round(max(similarities), 4),
        "mean_similarity": round(sum(similarities) / len(similarities), 4),
        "chunks": len(chunks),
    }


def self_check(question: str, answer: str, chunks: list[dict]) -> bool:
    """True when Gemini judges the answer grounded in the context.

    Fails OPEN (returns True) when the model is unreachable: a transient 503
    should not spam the ticket queue with escalations for answers that were
    probably fine.
    """
    context = "\n\n".join(f"[Source: {c['source']}]\n{c['content']}" for c in chunks)
    prompt = SELF_CHECK_PROMPT.format(
        context=context or "(no context retrieved)",
        question=question,
        answer=answer,
    )
    try:
        verdict = llm.generate(prompt)
    except llm.ModelUnavailable:
        return True
    return verdict.strip().upper().startswith("SUPPORTED")


def assess(question: str, answer: str, chunks: list[dict]) -> dict:
    """Run both signals and decide. Returns everything the caller needs to
    report the decision and explain it."""
    confidence = retrieval_confidence(chunks)
    low_retrieval = confidence["top_similarity"] < SIMILARITY_THRESHOLD

    # Only pay for the self-check when retrieval already looked good --
    # a low-similarity answer is being escalated regardless.
    grounded = True
    if not low_retrieval:
        grounded = self_check(question, answer, chunks)

    reasons = []
    if low_retrieval:
        reasons.append("low_retrieval_similarity")
    if not grounded:
        reasons.append("answer_not_grounded_in_context")

    return {
        "escalation_offered": bool(reasons),
        "reasons": reasons,
        "top_similarity": confidence["top_similarity"],
        "mean_similarity": confidence["mean_similarity"],
        "threshold": SIMILARITY_THRESHOLD,
        "self_check_ran": not low_retrieval,
        "self_check_grounded": grounded,
    }


def create_ticket(user, conversation_id: str | None, reason: str) -> str | None:
    """Open a support ticket for the supervisor queue.

    Deduped: a user with an open ticket for the same conversation does not get
    a second one. Without this, every low-confidence turn in one conversation
    would file its own ticket and bury the queue.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id FROM support_tickets
               WHERE user_id = %s AND tenant_id = %s AND status = 'open'
                 AND conversation_id IS NOT DISTINCT FROM %s
               LIMIT 1""",
            (user["linked_id"], user["tenant_id"], conversation_id),
        )
        existing = cur.fetchone()
        if existing:
            cur.close()
            return existing[0]

        cur.execute(
            """INSERT INTO support_tickets
                   (conversation_id, user_id, reason, status, tenant_id)
               VALUES (%s, %s, %s, 'open', %s)
               RETURNING id""",
            (conversation_id, user["linked_id"], reason, user["tenant_id"]),
        )
        ticket_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return ticket_id
    finally:
        conn.close()
