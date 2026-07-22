import os
from dotenv import load_dotenv
from google import genai
import psycopg2

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def get_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"])

def embed_query(question: str) -> list[float]:
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=question
    )
    return result.embeddings[0].values

def retrieve_chunks(question: str, top_k: int = 5) -> list[dict]:
    """Embed the question and find the top_k most similar chunks."""
    query_vector = embed_query(question)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT source_document, chunk_index, content,
               embedding <=> %s::vector AS distance
        FROM knowledge_chunks
        ORDER BY distance
        LIMIT %s
        """,
        (query_vector, top_k)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {"source": r[0], "chunk_index": r[1], "content": r[2], "distance": r[3]}
        for r in rows
    ]


if __name__ == "__main__":
    results = retrieve_chunks("test question here")
    for r in results:
        print(f"[{r['source']} #{r['chunk_index']}] dist={r['distance']:.3f}")
        print(r['content'][:100])
        print()