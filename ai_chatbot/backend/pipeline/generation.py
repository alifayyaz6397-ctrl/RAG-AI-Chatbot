import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def generate_answer(question: str, chunks: list[dict], student_context: str | None = None):

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
        model="gemini-3.5-flash",
        contents=prompt
    )

    for chunk in response:
        if chunk.text:
            yield chunk.text


if __name__ == "__main__":
    from retrieval import retrieve_chunks
    from students import get_student_context

    question = input("Ask a question: ")
    reg = input("Registration number (optional, press enter to skip): ").strip()

    student_ctx = get_student_context(reg) if reg else None
    chunks = retrieve_chunks(question)

    print("\nAnswer:\n")
    for piece in generate_answer(question, chunks, student_ctx):
        print(piece, end="", flush=True)