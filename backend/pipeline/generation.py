import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def generate_answer(question: str, chunks: list[dict]):

    context = "\n\n".join(
        f"[Source: {c['source']}]\n{c['content']}"
        for c in chunks
    )

    prompt = f"""
Answer the question using only the context below.
If the context doesn't contain the answer, say so.

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

    question = input("Ask a question: ")

    chunks = retrieve_chunks(question)

    print("\nAnswer:\n")

    for piece in generate_answer(question, chunks):
        print(piece, end="", flush=True)