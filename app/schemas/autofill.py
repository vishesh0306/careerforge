from typing import Optional

from pydantic import BaseModel, Field


class AutofillDraftRequest(BaseModel):
    resume_id: int = Field(..., description="Which of your resumes to use for contact info and the uploaded file.")


class AutofillDraftResponse(BaseModel):
    id: int
    job_listing_id: int
    resume_id: int
    ats_platform: str
    status: str
    filled_fields: dict[str, bool] = Field(
        default_factory=dict, description="Which fields were found and filled on the form."
    )
    screenshot_data_uri: Optional[str] = Field(None, description="PNG screenshot of the filled form state.")
    submitted: bool = Field(
        False, description="Always false — no code path in this feature is capable of submitting an application."
    )
    error: Optional[str] = None
