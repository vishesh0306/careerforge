import asyncio
from unittest.mock import AsyncMock, patch

from app.core.db import SessionLocal
from app.models import JobListing, PipelineRun, Resume, User
from app.services.ats_scoring import ATSScoreResult
from app.workers.job_search_worker import run_job_search


def _make_run_and_listings():
    session = SessionLocal()
    user = User(email="phase8-worker-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)

    resume = Resume(
        user_id=user.id,
        structured_content={
            "contact": {"name": "T", "email": "", "phone": "", "location": "", "links": []},
            "summary": "",
            "skills": {"languages": ["Python"], "frameworks": [], "tools": [], "cloud_devops": []},
            "experience": [],
            "projects": [],
            "education": [],
            "certifications": [],
        },
        version=1,
    )
    session.add(resume)
    session.commit()
    session.refresh(resume)

    listing_a = JobListing(
        source="adzuna", external_id="worker-test-a", title="Job A", company="X", jd_text="needs python", url="http://x/a"
    )
    listing_b = JobListing(
        source="adzuna", external_id="worker-test-b", title="Job B", company="Y", jd_text="needs java", url="http://x/b"
    )
    session.add_all([listing_a, listing_b])
    session.commit()
    session.refresh(listing_a)
    session.refresh(listing_b)

    run = PipelineRun(
        user_id=user.id,
        run_type="job_search",
        current_step="SEARCH_QUEUED",
        status="queued",
        context={"resume_id": resume.id, "role": "Backend", "ranked_results": []},
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    ids = {
        "user_id": user.id,
        "resume_id": resume.id,
        "run_id": run.id,
        "listing_ids": [listing_a.id, listing_b.id],
    }
    session.close()
    return ids


def _cleanup(ids):
    session = SessionLocal()
    session.query(PipelineRun).filter(PipelineRun.id == ids["run_id"]).delete()
    session.query(JobListing).filter(JobListing.id.in_(ids["listing_ids"])).delete(synchronize_session=False)
    session.query(Resume).filter(Resume.user_id == ids["user_id"]).delete()
    session.query(User).filter(User.id == ids["user_id"]).delete()
    session.commit()
    session.close()


def test_run_job_search_ranks_results_by_score():
    ids = _make_run_and_listings()
    try:
        score_a = ATSScoreResult(
            score=80.0, must_have_present=["Python"], must_have_missing=[], nice_to_have_present=[],
            nice_to_have_missing=[], semantic_similarity=0.8, semantic_fit_comment="great",
        )
        score_b = ATSScoreResult(
            score=20.0, must_have_present=[], must_have_missing=["Java"], nice_to_have_present=[],
            nice_to_have_missing=[], semantic_similarity=0.2, semantic_fit_comment="poor",
        )

        with (
            patch(
                "app.workers.job_search_worker.get_or_fetch_listing_ids",
                new=AsyncMock(return_value=ids["listing_ids"]),
            ),
            patch("app.workers.job_search_worker.cosine_similarity", return_value=0.5),
            patch("app.workers.job_search_worker.score_resume_against_jd", side_effect=[score_a, score_b]),
        ):
            asyncio.run(run_job_search(None, ids["run_id"]))

        session = SessionLocal()
        run = session.get(PipelineRun, ids["run_id"])
        assert run.current_step == "RESULTS_READY"
        assert run.status == "completed"
        results = run.context["ranked_results"]
        assert len(results) == 2
        assert results[0]["score"] == 80.0
        assert results[1]["score"] == 20.0
        session.close()
    finally:
        _cleanup(ids)


def test_run_job_search_skips_listing_on_scoring_failure():
    ids = _make_run_and_listings()
    try:
        score_ok = ATSScoreResult(
            score=50.0, must_have_present=[], must_have_missing=[], nice_to_have_present=[],
            nice_to_have_missing=[], semantic_similarity=0.5, semantic_fit_comment="ok",
        )

        with (
            patch(
                "app.workers.job_search_worker.get_or_fetch_listing_ids",
                new=AsyncMock(return_value=ids["listing_ids"]),
            ),
            patch("app.workers.job_search_worker.cosine_similarity", return_value=0.5),
            patch(
                "app.workers.job_search_worker.score_resume_against_jd",
                side_effect=[Exception("persistent rate limit"), score_ok],
            ),
        ):
            asyncio.run(run_job_search(None, ids["run_id"]))

        session = SessionLocal()
        run = session.get(PipelineRun, ids["run_id"])
        assert run.status == "completed"  # one failure must not crash the whole run
        results = run.context["ranked_results"]
        assert len(results) == 1
        assert results[0]["score"] == 50.0
        session.close()
    finally:
        _cleanup(ids)


def test_run_job_search_missing_resume_marks_failed_gracefully():
    ids = _make_run_and_listings()
    session = SessionLocal()
    run = session.get(PipelineRun, ids["run_id"])
    run.context = {**run.context, "resume_id": 99999999}
    session.commit()
    session.close()

    try:
        asyncio.run(run_job_search(None, ids["run_id"]))

        session = SessionLocal()
        run = session.get(PipelineRun, ids["run_id"])
        assert run.status == "failed"
        assert run.current_step == "RESULTS_READY"
        session.close()
    finally:
        _cleanup(ids)
