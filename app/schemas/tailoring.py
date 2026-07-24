from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.resume import ResumeContent
from app.services.ats_scoring import ATSScoreResult


class TailoringStartRequest(BaseModel):
    resume_id: int
    jd_text: str
    emphasis_focus: Optional[str] = Field(
        None,
        description="A specific tech/skill already in your resume to foreground for this application, "
        "e.g. 'Django'. If set, the tailored resume reorders existing bullets/skills to lead with "
        "emphasis_focus-relevant content and de-emphasize (never delete) less relevant stacks you also "
        "know — useful when you have multiple stacks (Django, Spring Boot, ...) and are applying to a "
        "role centered on just one of them.",
        examples=["Django"],
    )


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
