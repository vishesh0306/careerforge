from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.resume import ResumeContent


class StartRequest(BaseModel):
    user_id: int
    target_field: str
    self_description: str = Field(
        ...,
        description="Free-text description. If base_resume_id is not set, describe your whole background — "
        "this is a from-scratch build. If base_resume_id IS set, describe what's new, changed, or what you "
        "want added/updated this time — the builder already has your existing resume as a starting point.",
    )
    base_resume_id: Optional[int] = Field(
        None,
        description="Optional — an existing resume (yours) to build from instead of starting from scratch. "
        "The builder updates/extends it based on the conversation, preserving what's still accurate. "
        "Must belong to user_id.",
    )


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
