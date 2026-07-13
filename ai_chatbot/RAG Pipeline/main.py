from fastapi import FastAPI
from pydantic import BaseModel
from retrieval import retrieve_chunks
from generation import generate_answer

app = FastAPI()

class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    answer: str
    sources: list[str]

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    chunks = retrieve_chunks(request.question)
    answer = generate_answer(request.question, chunks)
    sources = list({c["source"] for c in chunks})
    return ChatResponse(answer=answer, sources=sources)