from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.errors import llm_error_response
from app.core.logging import log_transition
from app.core.ownership import get_owned_resume, get_owned_run
from app.graphs.jd_tailoring_graph import tailor_resume
from app.graphs.resume_builder_graph import BuilderState, resume_builder_graph
from app.models import InterviewPrep, JDAnalysis, JobListing, JobSearchPref, PipelineRun, Resume, User
from app.schemas.pipeline import PipelineStartRequest, PipelineStatusResponse, ShortlistItem
from app.schemas.resume import ResumeContent
from app.services.ats_scoring import extract_jd_terms, score_resume_against_jd
from app.services.interview_prep import generate_interview_prep
from app.services.llm_client import LLMError
from app.workers.job_search_worker import run_job_search

router = APIRouter()

RUN_TYPE = "full_pipeline"


def _get_run(run_id: int, current_user: User, db: Session) -> PipelineRun:
    return get_owned_run(run_id, RUN_TYPE, current_user, db)


@router.post("/run", response_model=PipelineStatusResponse, status_code=status.HTTP_201_CREATED)
async def start_pipeline(
    body: PipelineStartRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PipelineStatusResponse:
    context = {
        "user_id": current_user.id,
        "target_field": body.target_field,
        "emphasis_focus": body.emphasis_focus,
        "job_search_prefs": {
            "experience_years": body.experience_years,
            "location": body.location,
            "job_type": body.job_type,
            "work_mode": body.work_mode,
        },
        "top_n_to_tailor": body.top_n_to_tailor,
        "resume_id": None,
        "resume_builder_run_id": None,
        "job_search_run_id": None,
        "total_listings_found": None,
        "shortlist": [],
        "error": None,
    }

    if body.base_resume_id is not None:
        base_resume = get_owned_resume(body.base_resume_id, current_user, db)
        context["resume_id"] = base_resume.id
        current_step = "SEARCHING_JOBS"
        run_status = "in_progress"
    else:
        builder_state: BuilderState = {
            "target_field": body.target_field,
            "messages": [{"role": "candidate", "content": body.self_description}],
            "status": "INTAKE",
            "clarifying_question": None,
            "draft": None,
            "revision_feedback": None,
            "entry_point": "assess",
            "base_resume": None,
            "base_resume_id": None,
            "emphasis_focus": body.emphasis_focus,
            "captured_so_far": [],
            "resume_id": None,
        }
        try:
            builder_state = resume_builder_graph.invoke(builder_state)
        except LLMError as exc:
            raise llm_error_response(exc, "Resume builder") from exc

        builder_run = PipelineRun(
            user_id=current_user.id,
            run_type="resume_builder",
            current_step=builder_state["status"],
            status="completed" if builder_state["status"] == "FINALIZED" else "awaiting_input",
            context=dict(builder_state),
        )
        db.add(builder_run)
        db.flush()
        context["resume_builder_run_id"] = builder_run.id
        current_step = "AWAITING_RESUME"
        run_status = "awaiting_input"

    run = PipelineRun(
        user_id=current_user.id, run_type=RUN_TYPE, current_step=current_step, status=run_status, context=context
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    log_transition(RUN_TYPE, run.id, run.current_step, run.status)

    if current_step == "SEARCHING_JOBS":
        await _enqueue_job_search(run, db, request)

    return _status_response(run, db)


@router.get("/{run_id}/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    run_id: int, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PipelineStatusResponse:
    run = _get_run(run_id, current_user, db)
    await _try_advance(run, db, request)
    return _status_response(run, db)


async def _enqueue_job_search(run: PipelineRun, db: Session, request: Request) -> None:
    context = dict(run.context)
    prefs = context["job_search_prefs"]

    pref = JobSearchPref(
        user_id=context["user_id"],
        role=context["target_field"],
        experience_years=prefs.get("experience_years"),
        location=prefs.get("location"),
        job_type=prefs.get("job_type"),
        work_mode=prefs.get("work_mode"),
        expected_ctc=None,
    )
    db.add(pref)

    job_search_run = PipelineRun(
        user_id=context["user_id"],
        run_type="job_search",
        current_step="SEARCH_QUEUED",
        status="queued",
        context={
            "resume_id": context["resume_id"],
            "role": context["target_field"],
            "experience_years": prefs.get("experience_years"),
            "location": prefs.get("location"),
            "job_type": prefs.get("job_type"),
            "work_mode": prefs.get("work_mode"),
            "expected_ctc": None,
            "ranked_results": [],
        },
    )
    db.add(job_search_run)
    db.flush()

    context["job_search_run_id"] = job_search_run.id
    run.context = context
    run.current_step = "SEARCHING_JOBS"
    run.status = "in_progress"
    flag_modified(run, "context")
    db.commit()
    log_transition(RUN_TYPE, run.id, run.current_step, run.status, job_search_run_id=job_search_run.id)

    await request.app.state.arq_pool.enqueue_job(run_job_search.__name__, job_search_run.id)


async def _try_advance(run: PipelineRun, db: Session, request: Request) -> None:
    """Progresses the pipeline through as many stages as are currently ready, persisting after
    each transition. Safe to call repeatedly (including after a restart) — this is what makes the
    pipeline resumable purely by polling GET /status."""
    while True:
        context = dict(run.context)

        if run.current_step == "AWAITING_RESUME":
            builder_run = db.get(PipelineRun, context["resume_builder_run_id"])
            if builder_run.current_step != "FINALIZED":
                return
            context["resume_id"] = builder_run.context.get("resume_id")
            run.context = context
            flag_modified(run, "context")
            db.commit()
            await _enqueue_job_search(run, db, request)
            continue

        if run.current_step == "SEARCHING_JOBS":
            job_search_run = db.get(PipelineRun, context["job_search_run_id"])
            if job_search_run.status == "failed":
                context["error"] = job_search_run.context.get("error", "Job search failed")
                run.context = context
                run.current_step = "FAILED"
                run.status = "failed"
                flag_modified(run, "context")
                db.commit()
                log_transition(RUN_TYPE, run.id, run.current_step, run.status, error=context["error"])
                return
            if job_search_run.status != "completed":
                return
            context["total_listings_found"] = job_search_run.context.get("total_listings_found")
            ranked_results = job_search_run.context.get("ranked_results", [])
            run.context = context
            flag_modified(run, "context")
            db.commit()
            _tailor_shortlist(run, db, ranked_results)
            return

        return


def _tailor_shortlist(run: PipelineRun, db: Session, ranked_results: list[dict]) -> None:
    context = dict(run.context)
    top_n = context.get("top_n_to_tailor", 3)
    emphasis_focus = context.get("emphasis_focus")

    resume = db.get(Resume, context["resume_id"])
    resume_content = ResumeContent.model_validate(resume.structured_content)

    shortlist = []
    for rank, item in enumerate(ranked_results):
        entry = {
            "listing_id": item["listing_id"],
            "title": item["title"],
            "company": item.get("company"),
            "url": item["url"],
            "original_score": item["score"],
            "tailored_resume_id": None,
            "tailored_score": None,
            "interview_prep_id": None,
        }

        if rank >= top_n:
            shortlist.append(entry)
            continue

        try:
            listing = db.get(JobListing, item["listing_id"])
            jd_text = listing.jd_text if listing and listing.jd_text else f"{item['title']} at {item.get('company') or 'an unlisted company'}"

            jd_terms = extract_jd_terms(jd_text)
            baseline = score_resume_against_jd(resume_content, jd_text, jd_terms=jd_terms)

            content_for_prep = resume_content
            analysis_resume_id = resume.id
            score_for_analysis = baseline

            if emphasis_focus:
                tailored_content = tailor_resume(resume_content, jd_text, confirmed_gaps=[], emphasis_focus=emphasis_focus)
                tailored_score = score_resume_against_jd(
                    tailored_content, jd_text, baseline.candidate_years_experience, jd_terms
                )
                tailored_resume = Resume(
                    user_id=resume.user_id,
                    structured_content=tailored_content.model_dump(),
                    version=resume.version + 1,
                    source="tailored",
                    label=f"Tailored — {item['title']}",
                    parent_resume_id=resume.id,
                )
                db.add(tailored_resume)
                db.flush()
                entry["tailored_resume_id"] = tailored_resume.id
                entry["tailored_score"] = tailored_score.score
                content_for_prep = tailored_content
                analysis_resume_id = tailored_resume.id
                score_for_analysis = tailored_score
            else:
                entry["tailored_score"] = baseline.score

            analysis = JDAnalysis(
                resume_id=analysis_resume_id,
                jd_text=jd_text,
                score=score_for_analysis.score,
                breakdown=score_for_analysis.model_dump(),
            )
            db.add(analysis)
            db.flush()

            try:
                prep_result = generate_interview_prep(content_for_prep, jd_text, analysis.breakdown)
                prep = InterviewPrep(
                    jd_analysis_id=analysis.id,
                    questions=[q.model_dump() for q in prep_result.questions],
                )
                db.add(prep)
                db.flush()
                entry["interview_prep_id"] = prep.id
            except LLMError:
                pass  # interview prep is a nice-to-have per listing — don't drop the whole listing for it
        except LLMError:
            pass  # skip enrichment for this listing rather than failing the whole shortlist

        shortlist.append(entry)

    context["shortlist"] = shortlist
    run.context = context
    run.current_step = "READY"
    run.status = "completed"
    flag_modified(run, "context")
    db.commit()
    log_transition(RUN_TYPE, run.id, run.current_step, run.status, shortlist_size=len(shortlist))


def _status_response(run: PipelineRun, db: Session) -> PipelineStatusResponse:
    context = run.context or {}
    message = None
    if run.current_step == "AWAITING_RESUME":
        message = (
            f"Awaiting resume builder input — respond via /resume-builder/"
            f"{context.get('resume_builder_run_id')}/respond or /confirm, then poll this status again."
        )
    elif run.current_step == "SEARCHING_JOBS":
        message = "Job search is running in the background — poll this status again shortly."

    return PipelineStatusResponse(
        run_id=run.id,
        current_step=run.current_step,
        status=run.status,
        resume_id=context.get("resume_id"),
        resume_builder_run_id=context.get("resume_builder_run_id"),
        job_search_run_id=context.get("job_search_run_id"),
        total_listings_found=context.get("total_listings_found"),
        shortlist=[ShortlistItem(**item) for item in context.get("shortlist", [])],
        error=context.get("error"),
        message=message,
    )
