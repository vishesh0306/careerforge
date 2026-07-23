from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.resume import ResumeContent


class StartRequest(BaseModel):
    user_id: int
    target_field: str
    self_description: str


class RespondRequest(BaseModel):
    answer: str


class ConfirmRequest(BaseModel):
    approved: bool
    feedback: Optional[str] = Field(default=None, description="Required when approved is false")


class BuilderStateResponse(BaseModel):
    run_id: int
    status: str
    clarifying_question: Optional[str] = None
    draft: Optional[ResumeContent] = None
    resume_id: Optional[int] = None
