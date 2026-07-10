import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def embed_text(text: str) -> list[float]:
    """Get a 3072-dim embedding vector for a piece of text."""
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text
    )
    return result.embeddings[0].values


if __name__ == "__main__":
    vec = embed_text("Testing the embedding wrapper.")
    print(f"Got vector of length {len(vec)}")