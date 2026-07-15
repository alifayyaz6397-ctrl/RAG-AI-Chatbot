import tiktoken
from google import genai
import asyncpg
import pdfplumber
import asyncio
from DB.connection import get_connection


with pdfplumber.open("data/Resume .pdf") as pdf:            #extract text
    text=""
    for page in pdf.pages:
        text+=page.extract_text() or ""
        text+= "\n"

encoding=tiktoken.encoding_for_model("text-embedding-3-small")      

overlap=50
chunk=512
tokens=encoding.encode(text)    # make Tokens
print("Tokens: ", len(tokens))

chunks=[]
for i in range(0,len(tokens),chunk-overlap):    # make chunks
    chunk_tokens=tokens[i:i+chunk]
    chunk_text=encoding.decode(chunk_tokens)
    chunks.append(chunk_text)
print(f"Chunks: {len(chunks)}")

async def insert_chunks(conn,chunk,embedding,position):
    rows=await conn.execute("Insert into knowledge_chunks (source_document,chunk_index,content,embedding) values ($1,$2,$3,$4)","xxxxx" , position,chunk, str(embedding))
       
async def  main():
    conn = await get_connection()
    client=genai.Client()
    for i in range(len(chunks)):
        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=chunks[i]
            )
        embedding=result.embeddings[0].values
        await insert_chunks(conn,chunks[i],embedding,i)
    await conn.close()
asyncio.run(main())