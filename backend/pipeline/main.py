from fastapi import FastAPI
from pydantic import BaseModel
from retrieval import retrieve_chunks
from generation import generate_answer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    answer: str
    sources: list[str]


@app.post("/api/chat")
async def chat(request: ChatRequest):

    chunks = retrieve_chunks(request.question)

    return StreamingResponse(
        generate_answer(request.question, chunks),
        media_type="text/plain"
    )