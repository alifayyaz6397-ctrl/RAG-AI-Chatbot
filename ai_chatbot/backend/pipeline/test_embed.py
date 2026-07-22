import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

result = client.models.embed_content(
    model="gemini-embedding-001",
    contents="This is a test sentence."
)

print(len(result.embeddings[0].values))  # should print 3072