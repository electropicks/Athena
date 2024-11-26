import pymupdf
import pymupdf4llm


def extract_markdown_from_pdf(file):
    with pymupdf.Document(file) as pdf:
        return pymupdf4llm.to_markdown(pdf)