import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

def get_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"])

def store_chunk(source_document: str, chunk_index: int, content: str, embedding: list[float]):
    """Insert one chunk + its embedding into knowledge_chunks."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO knowledge_chunks (source_document, chunk_index, content, embedding)
        VALUES (%s, %s, %s, %s)
        """,
        (source_document, chunk_index, content, embedding)
    )
    conn.commit()
    cur.close()
    conn.close()

def chunk_already_exists(source_document: str, chunk_index: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM knowledge_chunks WHERE source_document = %s AND chunk_index = %s",
        (source_document, chunk_index)
    )
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists