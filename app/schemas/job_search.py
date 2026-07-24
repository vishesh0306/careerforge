from typing import Optional

from pydantic import BaseModel, Field


class JobSearchRequest(BaseModel):
    user_id: int
    resume_id: int
    role: str = Field(
        ...,
        description="Free-text job title to search for, e.g. 'Backend Developer', 'QA Engineer'. "
        "Matched against listing titles (Adzuna) or query text (JSearch/RemoteOK/Arbeitnow) — not a fixed list.",
        examples=["Backend Developer"],
    )
    experience_years: Optional[float] = Field(
        None,
        description="Your years of professional experience. Listings requiring more than "
        "~2 years above this are excluded from results outright, not just ranked lower.",
        examples=[1],
    )
    location: Optional[str] = Field(
        None,
        description="Free-text city/region, e.g. 'Bangalore', 'Gurgaon', 'Remote'. Not a fixed list.",
        examples=["Bangalore"],
    )
    job_type: Optional[str] = Field(
        None,
        description="One of: 'full_time', 'intern', 'contract' (case/spacing/underscore-insensitive — "
        "'fulltime', 'Full Time', 'full-time' all work). Anything else is accepted but has no filtering effect.",
        examples=["full_time"],
    )
    work_mode: Optional[str] = Field(
        None,
        description="One of: 'wfh' or 'remote' (both restrict JSearch/Arbeitnow to remote-only listings), "
        "'hybrid', 'onsite'. Only wfh/remote currently has an active filtering effect — hybrid/onsite are "
        "accepted but don't narrow results, since most listings are hybrid/onsite by default. Adzuna doesn't "
        "support remote-only filtering at all yet.",
        examples=["hybrid"],
    )
    expected_ctc: Optional[str] = Field(
        None,
        description="Free-text expected compensation, e.g. '15 LPA+'. Currently informational only — "
        "stored on the search preference but not used to filter or rank results.",
        examples=["15 LPA+"],
    )


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
    min_years_required: Optional[float] = None


class JobSearchResultsResponse(BaseModel):
    run_id: int
    status: str
    current_step: str
    total_listings_found: Optional[int] = None
    results: list[RankedListing] = []
    error: Optional[str] = None
