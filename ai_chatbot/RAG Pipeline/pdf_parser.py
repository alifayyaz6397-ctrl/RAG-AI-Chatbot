import pdfplumber

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF file, page by page."""
    full_text = []
    empty_pages = 0
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                full_text.append(text)
            else:
                empty_pages += 1

    if empty_pages > 0:
        print(f"WARNING: {empty_pages} page(s) had no extractable text (likely scanned/image pages)")

    return "\n".join(full_text)