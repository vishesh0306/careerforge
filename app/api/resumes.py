from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Resume, User
from app.schemas.resume import ResumeResponse
from app.services.llm_client import LLMError
from app.services.resume_parser import (
    ResumeParsingError,
    extract_text_from_docx,
    extract_text_from_pdf,
    parse_resume_text,
)

router = APIRouter()


@router.post("/upload", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Resume:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    filename = (file.filename or "").lower()
    if filename.endswith(".pdf"):
        file_type = "pdf"
    elif filename.endswith(".docx"):
        file_type = "docx"
    else:
        raise HTTPException(
            status_code=400, detail="Unsupported file type. Please upload a PDF or DOCX file."
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        text = extract_text_from_pdf(file_bytes) if file_type == "pdf" else extract_text_from_docx(file_bytes)
        structured_content = parse_resume_text(text)
    except ResumeParsingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"Resume parsing service failed: {exc}") from exc

    resume = Resume(user_id=user_id, structured_content=structured_content.model_dump(), version=1)
    db.add(resume)
    db.commit()
    db.refresh(resume)

    return resume
