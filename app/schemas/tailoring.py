from typing import Optional

from pydantic import BaseModel

from app.schemas.resume import ResumeContent
from app.services.ats_scoring import ATSScoreResult


class TailoringStartRequest(BaseModel):
    resume_id: int
    jd_text: str


class GapInfo(BaseModel):
    term: str
    category: str
    why_it_matters: str
    confirmed: Optional[bool] = None
    detail: Optional[str] = None


class GapConfirmation(BaseModel):
    term: str
    confirmed: bool
    detail: Optional[str] = None


class ConfirmGapsRequest(BaseModel):
    confirmations: list[GapConfirmation]


class TailoringStateResponse(BaseModel):
    run_id: int
    status: str
    jd_text: str
    original_score: ATSScoreResult
    gaps: list[GapInfo]
    tailored_resume_id: Optional[int] = None
    tailored_resume: Optional[ResumeContent] = None
    tailored_score: Optional[ATSScoreResult] = None
