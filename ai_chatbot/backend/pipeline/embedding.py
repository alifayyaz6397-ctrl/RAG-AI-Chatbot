import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def embed_text(text: str, max_retries: int = 5) -> list[float]:
    """Get a 3072-dim embedding vector for a piece of text, with retry on rate limits."""
    for attempt in range(max_retries):
        try:
            result = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text
            )
            return result.embeddings[0].values
        except errors.ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait_time = 2 ** attempt * 5  # 5s, 10s, 20s, 40s, 80s
                print(f"Rate limited. Waiting {wait_time}s before retry {attempt+1}/{max_retries}...")
                time.sleep(wait_time)
            else:
                raise
    raise RuntimeError("Max retries exceeded for embedding call")