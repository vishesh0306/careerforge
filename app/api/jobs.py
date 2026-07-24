from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import JobSearchPref, PipelineRun, Resume, User
from app.schemas.job_search import JobSearchRequest, JobSearchResultsResponse, JobSearchStartResponse
from app.workers.job_search_worker import run_job_search

router = APIRouter()

RUN_TYPE = "job_search"


@router.post("/search", response_model=JobSearchStartResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_job_search(
    body: JobSearchRequest, request: Request, db: Session = Depends(get_db)
) -> JobSearchStartResponse:
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {body.user_id} not found")
    resume = db.get(Resume, body.resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail=f"Resume {body.resume_id} not found")

    pref = JobSearchPref(
        user_id=body.user_id,
        role=body.role,
        experience_years=body.experience_years,
        location=body.location,
        job_type=body.job_type,
        work_mode=body.work_mode,
        expected_ctc=body.expected_ctc,
    )
    db.add(pref)

    run = PipelineRun(
        user_id=body.user_id,
        run_type=RUN_TYPE,
        current_step="SEARCH_QUEUED",
        status="queued",
        context={
            "resume_id": body.resume_id,
            "role": body.role,
            "experience_years": body.experience_years,
            "location": body.location,
            "job_type": body.job_type,
            "work_mode": body.work_mode,
            "expected_ctc": body.expected_ctc,
            "ranked_results": [],
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    await request.app.state.arq_pool.enqueue_job(run_job_search.__name__, run.id)

    return JobSearchStartResponse(run_id=run.id, status=run.current_step)


@router.get("/search/{run_id}/results", response_model=JobSearchResultsResponse)
def get_job_search_results(run_id: int, db: Session = Depends(get_db)) -> JobSearchResultsResponse:
    run = db.get(PipelineRun, run_id)
    if run is None or run.run_type != RUN_TYPE:
        raise HTTPException(status_code=404, detail=f"Job search run {run_id} not found")

    context = run.context or {}
    return JobSearchResultsResponse(
        run_id=run.id,
        status=run.status,
        current_step=run.current_step,
        total_listings_found=context.get("total_listings_found"),
        results=context.get("ranked_results", []),
    )
