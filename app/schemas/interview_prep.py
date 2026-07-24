from datetime import datetime

from pydantic import BaseModel

from app.services.interview_prep import InterviewQuestion


class InterviewPrepResponse(BaseModel):
    id: int
    jd_analysis_id: int
    questions: list[InterviewQuestion]
    created_at: datetime
