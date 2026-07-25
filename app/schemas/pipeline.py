from typing import Optional

from pydantic import BaseModel, Field, model_validator


class PipelineStartRequest(BaseModel):
    user_id: int
    target_field: str = Field(..., description="Target role — used for resume building (if needed) and job search.")

    base_resume_id: Optional[int] = Field(
        None,
        description="Use this existing resume instead of building a new one. Must belong to user_id. "
        "If omitted, self_description is required and a new resume is built first.",
    )
    self_description: Optional[str] = Field(
        None,
        description="Free-text background description, used to build a new resume if base_resume_id is not "
        "given. Required in that case.",
    )
    emphasis_focus: Optional[str] = Field(
        None,
        description="A specific tech/skill to foreground — applied both when building the resume and when "
        "tailoring it for each shortlisted job.",
        examples=["Django"],
    )

    experience_years: Optional[float] = Field(None, description="Your years of professional experience.")
    location: Optional[str] = Field(None, description="Free-text city/region, e.g. 'Bangalore', 'Remote'.")
    job_type: Optional[str] = Field(None, description="One of: 'full_time', 'intern', 'contract'.")
    work_mode: Optional[str] = Field(None, description="One of: 'wfh'/'remote', 'hybrid', 'onsite'.")

    top_n_to_tailor: int = Field(
        3,
        ge=0,
        le=10,
        description="How many top-ranked listings to tailor and generate interview prep for. Each one costs "
        "real LLM calls, so keep this small under tight quota. 0 returns the ranked shortlist without "
        "tailoring or prep.",
    )

    @model_validator(mode="after")
    def _require_resume_source(self) -> "PipelineStartRequest":
        if self.base_resume_id is None and not self.self_description:
            raise ValueError("Provide either base_resume_id (use an existing resume) or self_description (build a new one).")
        return self


class ShortlistItem(BaseModel):
    listing_id: int
    title: str
    company: Optional[str] = None
    url: str
    original_score: float
    tailored_resume_id: Optional[int] = None
    tailored_score: Optional[float] = None
    interview_prep_id: Optional[int] = None


class PipelineStatusResponse(BaseModel):
    run_id: int
    current_step: str
    status: str
    resume_id: Optional[int] = None
    resume_builder_run_id: Optional[int] = None
    job_search_run_id: Optional[int] = None
    total_listings_found: Optional[int] = None
    shortlist: list[ShortlistItem] = []
    error: Optional[str] = None
    message: Optional[str] = Field(None, description="What to do next, when the pipeline is waiting on you.")
