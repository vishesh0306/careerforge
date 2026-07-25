from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import PipelineRun, Resume, User


def get_owned_resume(resume_id: int, current_user: User, db: Session) -> Resume:
    """Fetches a resume, 404ing if it doesn't exist OR belongs to someone else — the same response
    either way, so ownership mismatches don't leak that a resume_id exists."""
    resume = db.get(Resume, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")
    return resume


def get_owned_run(run_id: int, run_type: str, current_user: User, db: Session) -> PipelineRun:
    run = db.get(PipelineRun, run_id)
    if run is None or run.run_type != run_type or run.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"{run_type} run {run_id} not found")
    return run
