import os
from dotenv import load_dotenv
from google import genai
from storage import get_connection
import json

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def generate_answer(question: str, chunks: list[dict], user,student_context: str | None = None):

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

    response = client.models.generate_content_stream(
        model="gemini-3.6-flash",
        contents=prompt
    )
    full_answer=""
    for chunk in response:
        if chunk.text:
            full_answer+=chunk.text
            yield chunk.text
    messages=[
        {"role":"user", "content":question},
        {"role":"assistant","content":full_answer,"retrieved_chunk_id":[c["id"] for c in chunks if "id" in c ]}
    ]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO conversations (user_id, role, messages, tenant_id)
           VALUES (%s, %s, %s, %s)""",
        (user["linked_id"], user["role"], json.dumps(messages), user["tenant_id"])
    )
    conn.commit()
    cur.close()
    conn.close()
            


