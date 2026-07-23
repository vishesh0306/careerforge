import io

import pdfplumber
from docx import Document

from app.schemas.resume import ResumeContent
from app.services.llm_client import LLMError, llm_client

RESUME_EXTRACTION_PROMPT = """You are extracting structured resume data from the raw resume text below.

Rules:
- Extract ONLY information explicitly present in the text.
- Do NOT invent, infer, guess, or embellish names, dates, companies, titles, skills, or achievements that are not literally stated in the text.
- If a field is not present in the source text, leave it as an empty string or an empty list.
- Preserve the original wording of experience bullet points as closely as possible; do not add quantification, metrics, or claims that are not already in the source.

Resume text:
---
{text}
---
"""


class ResumeParsingError(Exception):
    """Raised when a resume file cannot be read or parsed into structured content."""


def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages_text = [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:
        raise ResumeParsingError(f"Could not read PDF file: {exc}") from exc

    text = "\n".join(pages_text).strip()
    if not text:
        raise ResumeParsingError(
            "No extractable text found in this PDF (it may be a scanned image without a text layer)."
        )
    return text


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        document = Document(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ResumeParsingError(f"Could not read DOCX file: {exc}") from exc

    text = "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    if not text:
        raise ResumeParsingError("No extractable text found in this DOCX file.")
    return text


def parse_resume_text(text: str) -> ResumeContent:
    prompt = RESUME_EXTRACTION_PROMPT.format(text=text)
    try:
        return llm_client.generate_structured(prompt, ResumeContent)
    except LLMError as exc:
        raise ResumeParsingError(f"Failed to parse resume content: {exc}") from exc
