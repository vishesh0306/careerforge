from typing import Optional

from pydantic import BaseModel


class JobSearchRequest(BaseModel):
    user_id: int
    resume_id: int
    role: str
    experience_years: Optional[float] = None
    location: Optional[str] = None
    job_type: Optional[str] = None
    work_mode: Optional[str] = None
    expected_ctc: Optional[str] = None


class JobSearchStartResponse(BaseModel):
    run_id: int
    status: str


class RankedListing(BaseModel):
    listing_id: int
    source: str
    title: str
    company: Optional[str] = None
    url: str
    location: Optional[str] = None
    score: float
    must_have_missing: list[str]
    semantic_fit_comment: str


class JobSearchResultsResponse(BaseModel):
    run_id: int
    status: str
    current_step: str
    total_listings_found: Optional[int] = None
    results: list[RankedListing] = []
    error: Optional[str] = None
