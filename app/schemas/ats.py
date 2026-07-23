from pydantic import BaseModel


class ScoreAgainstJDRequest(BaseModel):
    resume_id: int
    jd_text: str


class ScoreAgainstRoleRequest(BaseModel):
    resume_id: int
    role: str
    seniority: str


class ATSScoreResponse(BaseModel):
    jd_analysis_id: int
    jd_text: str
    score: float
    must_have_present: list[str]
    must_have_missing: list[str]
    nice_to_have_present: list[str]
    nice_to_have_missing: list[str]
    semantic_similarity: float
    semantic_fit_comment: str
