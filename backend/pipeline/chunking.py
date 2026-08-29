# import tiktoken

# def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
#     """Split text into overlapping chunks based on token count."""
#     encoding = tiktoken.get_encoding("cl100k_base")
#     tokens = encoding.encode(text)

#     chunks = []
#     start = 0
#     while start < len(tokens):
#         end = start + chunk_size
#         chunk_tokens = tokens[start:end]
#         chunks.append(encoding.decode(chunk_tokens))
#         start += chunk_size - overlap

#     return chunks
import tiktoken 
import re 

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Split FAQ-style text into chunks, treating each Q&A pair as atomic.
    Never splits a single Q&A across chunks. Packs multiple small Q&As
    together up to chunk_size tokens. Falls back to token-slicing only
    for a single Q&A pair that individually exceeds chunk_size.
    """
    encoding = tiktoken.get_encoding("cl100k_base")

    # Split on blank lines between Q&A pairs (each pair separated by \n\n)
    qa_units = [u.strip() for u in re.split(r"\n\s*\n", text) if u.strip()]

    chunks = []
    current_chunk = []
    current_tokens = 0

    for unit in qa_units:
        unit_tokens = len(encoding.encode(unit))

        # Single Q&A too large on its own -- fall back to raw slicing for just this unit
        if unit_tokens > chunk_size:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk, current_tokens = [], 0
            tokens = encoding.encode(unit)
            start = 0
            while start < len(tokens):
                end = start + chunk_size
                chunks.append(encoding.decode(tokens[start:end]))
                start += chunk_size - overlap
            continue

        # Would adding this unit overflow the chunk?
        if current_tokens + unit_tokens > chunk_size:
            chunks.append("\n\n".join(current_chunk))
            current_chunk, current_tokens = [], 0

        current_chunk.append(unit)
        current_tokens += unit_tokens

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks