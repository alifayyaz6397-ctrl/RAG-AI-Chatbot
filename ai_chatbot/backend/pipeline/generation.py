import os
from dotenv import load_dotenv
from google import genai
from storage import get_connection
import json
import uuid

load_dotenv()

def create_conversation_id():
    return f"conv-{uuid.uuid4()}"



conversation_id = create_conversation_id()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def generate_answer(question: str, chunks: list[dict], user, session_id ,isNewSession,conv_id,student_context: str | None = None):

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
        """INSERT INTO conversations (id,user_id, role, messages, tenant_id, session_id)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (conv_id,user["linked_id"], user["role"], json.dumps(messages), user["tenant_id"],session_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    if(isNewSession):
        generate_session_title(question,full_answer,session_id)
            

def generate_session_title(question: str, answer: str,session_id:str) -> str:
    prompt = f"""Generate a short, descriptive title (max 6 words, no quotes, no punctuation at the end) for this conversation based on its first exchange.

Question: {question}
Answer: {answer[:300]}

Title:"""

    response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents=prompt,
    config={
        "max_output_tokens": 200
    }
)


    if response.text:
        title = response.text.strip().strip('"').strip("'")
    else:
        title = "New Chat"
    # return title[:60]  # hard safety cap on length
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
            """INSERT INTO session_titles (title,session_id)
               VALUES (%s, %s)""",
            (title,session_id)
        )
    conn.commit()
    cur.close()
    conn.close()
    