import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def get_connection():
    return await asyncpg.connect(os.getenv("DB"))