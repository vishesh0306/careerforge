from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.errors import llm_error_response
from app.core.ownership import get_owned_resume
from app.models import InterviewPrep, JDAnalysis, User
from app.schemas.interview_prep import InterviewPrepResponse
from app.schemas.resume import ResumeContent
from app.services.interview_prep import generate_interview_prep
from app.services.llm_client import LLMError

router = APIRouter()


@router.post("/{jd_analysis_id}", response_model=InterviewPrepResponse, status_code=status.HTTP_201_CREATED)
def generate_prep_for_jd_analysis(
    jd_analysis_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InterviewPrepResponse:
    analysis = db.get(JDAnalysis, jd_analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail=f"JD analysis {jd_analysis_id} not found")

    resume = get_owned_resume(analysis.resume_id, current_user, db)

    content = ResumeContent.model_validate(resume.structured_content)
    try:
        result = generate_interview_prep(content, analysis.jd_text, analysis.breakdown)
    except LLMError as exc:
        raise llm_error_response(exc, "Interview prep generation") from exc

    prep = InterviewPrep(
        jd_analysis_id=jd_analysis_id,
        questions=[q.model_dump() for q in result.questions],
    )
    db.add(prep)
    db.commit()
    db.refresh(prep)

    return InterviewPrepResponse(
        id=prep.id, jd_analysis_id=jd_analysis_id, questions=result.questions, created_at=prep.created_at
    )
