from fastapi import FastAPI
from pydantic import BaseModel
from retrieval import retrieve_chunks
from generation import generate_answer
from students import get_student_context
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
    registration_number: str | None = None


@app.post("/api/chat")
async def chat(request: ChatRequest):

    student_ctx = None
    if request.registration_number:
        student_ctx = get_student_context(request.registration_number)

    chunks = retrieve_chunks(request.question)

    return StreamingResponse(
        generate_answer(request.question, chunks, student_ctx),
        media_type="text/plain"
    )