from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import JDAnalysis, Resume
from app.schemas.ats import ATSScoreResponse, ScoreAgainstJDRequest, ScoreAgainstRoleRequest
from app.schemas.resume import ResumeContent
from app.services.ats_scoring import score_resume_against_jd, synthesize_ideal_jd
from app.services.llm_client import LLMError

router = APIRouter()


def _get_resume(resume_id: int, db: Session) -> Resume:
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")
    return resume


def _score_and_store(resume: Resume, jd_text: str, db: Session) -> ATSScoreResponse:
    content = ResumeContent.model_validate(resume.structured_content)
    try:
        result = score_resume_against_jd(content, jd_text)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"ATS scoring failed: {exc}") from exc

    analysis = JDAnalysis(
        resume_id=resume.id,
        jd_text=jd_text,
        score=result.score,
        breakdown=result.model_dump(),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    return ATSScoreResponse(jd_analysis_id=analysis.id, jd_text=jd_text, **result.model_dump())


@router.post("/score-against-jd", response_model=ATSScoreResponse, status_code=status.HTTP_201_CREATED)
def score_against_jd(body: ScoreAgainstJDRequest, db: Session = Depends(get_db)) -> ATSScoreResponse:
    resume = _get_resume(body.resume_id, db)
    return _score_and_store(resume, body.jd_text, db)


@router.post("/score-against-role", response_model=ATSScoreResponse, status_code=status.HTTP_201_CREATED)
def score_against_role(body: ScoreAgainstRoleRequest, db: Session = Depends(get_db)) -> ATSScoreResponse:
    resume = _get_resume(body.resume_id, db)
    try:
        jd_text = synthesize_ideal_jd(body.role, body.seniority)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to synthesize role JD: {exc}") from exc
    return _score_and_store(resume, jd_text, db)
