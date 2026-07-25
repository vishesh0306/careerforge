from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.errors import llm_error_response
from app.core.ownership import get_owned_resume
from app.models import Resume, User
from app.schemas.resume import ResumeContent, ResumeContentPatch, ResumeResponse, merge_resume_patch
from app.services.llm_client import LLMError
from app.services.resume_parser import (
    ResumeParsingError,
    extract_text_from_docx,
    extract_text_from_pdf,
    parse_resume_text,
)
from app.services.resume_renderer import render_resume_pdf

router = APIRouter()


@router.post("/upload", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Resume:
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
        raise llm_error_response(exc, "Resume parsing") from exc

    resume = Resume(
        user_id=current_user.id,
        structured_content=structured_content.model_dump(),
        version=1,
        source="uploaded",
        label="Uploaded resume",
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)

    return resume


@router.get("", response_model=list[ResumeResponse])
def list_resumes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Resume]:
    return (
        db.query(Resume)
        .filter(Resume.user_id == current_user.id)
        .order_by(Resume.created_at.desc())
        .all()
    )


@router.patch("/{resume_id}", response_model=ResumeResponse)
def patch_resume(
    resume_id: int,
    body: ResumeContentPatch,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Resume:
    resume = get_owned_resume(resume_id, current_user, db)

    if not body.model_fields_set:
        raise HTTPException(status_code=400, detail="No fields provided to patch")

    merged = merge_resume_patch(resume.structured_content, body)
    try:
        ResumeContent.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    resume.structured_content = merged
    db.commit()
    db.refresh(resume)

    return resume


@router.get("/{resume_id}/pdf")
def download_resume_pdf(
    resume_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    resume = get_owned_resume(resume_id, current_user, db)

    content = ResumeContent.model_validate(resume.structured_content)
    pdf_bytes = render_resume_pdf(content)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume_{resume_id}.pdf"'},
    )
