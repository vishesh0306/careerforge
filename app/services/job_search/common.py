from pydantic import BaseModel


class JobSearchQuery(BaseModel):
    role: str
    location: str | None = None
    job_type: str | None = None  # full_time / intern / contract
    work_mode: str | None = None  # wfh / hybrid / onsite
    experience_years: float | None = None


class NormalizedListing(BaseModel):
    source: str
    external_id: str
    title: str
    company: str | None = None
    jd_text: str | None = None
    url: str
    location: str | None = None
