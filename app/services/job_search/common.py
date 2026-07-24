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


def normalize_job_type(job_type: str | None) -> str:
    """Canonicalizes free-text job_type input (e.g. "fulltime", "Full-Time",
    "full_time" all collapse to "fulltime") so source clients don't each need
    their own ad-hoc matching — and don't silently no-op on a spelling variant."""
    return (job_type or "").replace("-", "").replace("_", "").replace(" ", "").lower()
