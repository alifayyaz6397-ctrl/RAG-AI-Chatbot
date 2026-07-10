import pdfplumber

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF file, page by page."""
    full_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text.append(text)
    return "\n".join(full_text)


if __name__ == "__main__":
    import sys
    text = extract_text_from_pdf(sys.argv[1])
    print(f"Extracted {len(text)} characters")
    print(text[:500])  # preview first 500 chars