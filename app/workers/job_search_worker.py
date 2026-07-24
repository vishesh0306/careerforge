import logging

from arq.connections import RedisSettings

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import JobListing, PipelineRun, Resume
from app.schemas.resume import ResumeContent
from app.services.ats_scoring import resume_content_to_text, score_resume_against_jd
from app.services.embeddings import cosine_similarity
from app.services.job_search.aggregator import get_or_fetch_listing_ids
from app.services.job_search.common import JobSearchQuery

logger = logging.getLogger(__name__)

# Caps LLM-based ATS scoring calls per search run — job search can return far more
# listings than the free-tier Gemini quota can score in one run (see Phase 6 notes).
MAX_LISTINGS_TO_SCORE = 15


async def _search_and_rank(session, context: dict, resume: Resume) -> tuple[list[dict], int]:
    query = JobSearchQuery(
        role=context["role"],
        location=context.get("location"),
        job_type=context.get("job_type"),
        work_mode=context.get("work_mode"),
        experience_years=context.get("experience_years"),
    )

    listing_ids = await get_or_fetch_listing_ids(query)
    resume_content = ResumeContent.model_validate(resume.structured_content)
    resume_text = resume_content_to_text(resume_content)

    # Pre-rank by cheap, free, local embedding similarity (no LLM call) across ALL
    # listings before spending LLM quota on the capped subset — otherwise capping by
    # arbitrary DB order could systematically exclude entire sources from scoring.
    listings = [session.get(JobListing, lid) for lid in listing_ids]
    listings = [listing for listing in listings if listing is not None]
    pre_ranked = sorted(
        listings,
        key=lambda listing: cosine_similarity(
            resume_text, listing.jd_text or f"{listing.title} at {listing.company or ''}"
        ),
        reverse=True,
    )

    ranked_results = []
    for listing in pre_ranked[:MAX_LISTINGS_TO_SCORE]:
        jd_text = listing.jd_text or f"{listing.title} at {listing.company or 'an unlisted company'}"
        try:
            score_result = score_resume_against_jd(resume_content, jd_text)
        except Exception as exc:
            # A single listing's scoring failure (e.g. retries exhausted on a
            # persistent rate limit) must never abort the whole search run.
            logger.warning("Skipping listing %s — scoring failed: %s", listing.id, exc)
            continue

        ranked_results.append(
            {
                "listing_id": listing.id,
                "source": listing.source,
                "title": listing.title,
                "company": listing.company,
                "url": listing.url,
                "location": listing.location,
                "score": score_result.score,
                "must_have_missing": score_result.must_have_missing,
                "semantic_fit_comment": score_result.semantic_fit_comment,
            }
        )

    ranked_results.sort(key=lambda r: r["score"], reverse=True)
    return ranked_results, len(listing_ids)


async def run_job_search(ctx, pipeline_run_id: int) -> None:
    session = SessionLocal()
    try:
        run = session.get(PipelineRun, pipeline_run_id)
        if run is None:
            logger.error("Job search worker: pipeline_run %s not found", pipeline_run_id)
            return

        context = dict(run.context)
        resume_id = context["resume_id"]
        resume = session.get(Resume, resume_id)
        if resume is None:
            run.status = "failed"
            run.current_step = "RESULTS_READY"
            context["error"] = f"Resume {resume_id} not found"
            context["ranked_results"] = []
            run.context = context
            session.commit()
            return

        try:
            ranked_results, total_found = await _search_and_rank(session, context, resume)
        except Exception as exc:
            # A run must never be left silently stuck at SEARCH_QUEUED forever —
            # any unexpected failure (e.g. a DB constraint error) is surfaced as a
            # failed run instead of hanging indefinitely.
            logger.exception("Job search run %s failed unexpectedly", pipeline_run_id)
            session.rollback()
            run = session.get(PipelineRun, pipeline_run_id)
            context = dict(run.context)
            context["error"] = str(exc)
            context["ranked_results"] = []
            run.context = context
            run.current_step = "RESULTS_READY"
            run.status = "failed"
            session.commit()
            return

        context["ranked_results"] = ranked_results
        context["total_listings_found"] = total_found
        run.context = context
        run.current_step = "RESULTS_READY"
        run.status = "completed"
        session.commit()
    finally:
        session.close()


class WorkerSettings:
    functions = [run_job_search]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
