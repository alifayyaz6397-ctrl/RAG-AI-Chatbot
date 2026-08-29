import sys
import os
import time
from pdf_parser import extract_text_from_pdf
from chunking import chunk_text
from embedding import embed_text
from storage import store_chunk, chunk_already_exists

def ingest_document(pdf_path: str):
    print(f"Extracting text from {pdf_path}...")
    text = extract_text_from_pdf(pdf_path)
    print(f"Extracted {len(text)} characters")

    print("Chunking...")
    chunks = chunk_text(text)
    print(f"Created {len(chunks)} chunks")

    for i, chunk in enumerate(chunks):
        if chunk_already_exists(pdf_path, i):
            print(f"Chunk {i+1}/{len(chunks)} already stored, skipping...")
            continue
        print(f"Embedding + storing chunk {i+1}/{len(chunks)}...")
        vector = embed_text(chunk)
        store_chunk(pdf_path, i, chunk, vector)
        time.sleep(0.5)

    print("Done.")

# if __name__ == "__main__":
#     if len(sys.argv) != 2:
#         print("Usage: python ingest.py <path_to_pdf>")
#         sys.exit(1)
#     ingest_document(sys.argv[1])
if __name__ == "__main__":
    pdf_path = input("Enter the path to the PDF file: ").strip().strip('"')
    
    if not pdf_path:
        print("No path entered. Exiting.")
        sys.exit(1)
    
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        sys.exit(1)
    
    if not pdf_path.lower().endswith(".pdf"):
        print("Warning: file doesn't end in .pdf, continuing anyway.")
    
    ingest_document(pdf_path)