from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.graphs.resume_builder_graph import AssessmentResult
from app.main import app
from app.models import InterviewPrep, JDAnalysis, JobListing, JobSearchPref, PipelineRun, Resume, User
from app.schemas.resume import ContactInfo, ResumeContent
from app.services.ats_scoring import JDTerms
from tests.conftest import auth_headers_for

RESUME_CONTENT = {
    "contact": {"name": "Pipeline Test", "email": "pt@example.com", "phone": "", "location": "", "links": []},
    "summary": "",
    "skills": {"languages": ["Python"], "frameworks": ["Django"], "tools": [], "cloud_devops": [], "other": []},
    "experience": [
        {"company": "Acme", "title": "Backend Engineer", "start_date": "2021", "end_date": "Present", "bullets": []}
    ],
    "projects": [],
    "education": [],
    "certifications": [],
    "achievements": [],
}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def user_with_resume():
    session = SessionLocal()
    user = User(email="pipeline-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)

    resume = Resume(user_id=user.id, structured_content=RESUME_CONTENT, version=1, source="uploaded")
    session.add(resume)
    session.commit()
    session.refresh(resume)
    ids = (user.id, resume.id)
    session.close()

    yield ids

    session = SessionLocal()
    resume_ids = [r.id for r in session.query(Resume).filter(Resume.user_id == ids[0]).all()]
    jda_ids = [j.id for j in session.query(JDAnalysis).filter(JDAnalysis.resume_id.in_(resume_ids)).all()] if resume_ids else []
    if jda_ids:
        session.query(InterviewPrep).filter(InterviewPrep.jd_analysis_id.in_(jda_ids)).delete(synchronize_session=False)
        session.query(JDAnalysis).filter(JDAnalysis.id.in_(jda_ids)).delete(synchronize_session=False)
    session.query(PipelineRun).filter(PipelineRun.user_id == ids[0]).delete()
    session.query(JobSearchPref).filter(JobSearchPref.user_id == ids[0]).delete()
    session.query(Resume).filter(Resume.user_id == ids[0]).delete()
    session.query(User).filter(User.id == ids[0]).delete()
    session.commit()
    session.close()


@pytest.fixture()
def auth_headers(user_with_resume):
    user_id, _ = user_with_resume
    return auth_headers_for(user_id)


def _base_body(**overrides):
    body = {"target_field": "Backend Engineer", "top_n_to_tailor": 1}
    body.update(overrides)
    return body


# --- validation ---


def test_start_requires_base_resume_id_or_self_description(client, user_with_resume, auth_headers):
    response = client.post("/pipeline/run", json=_base_body(), headers=auth_headers)
    assert response.status_code == 422


def test_start_without_auth_returns_403(client):
    response = client.post("/pipeline/run", json=_base_body(base_resume_id=1))
    assert response.status_code == 403


def test_start_with_nonexistent_base_resume_returns_404(client, user_with_resume, auth_headers):
    response = client.post("/pipeline/run", json=_base_body(base_resume_id=99999999), headers=auth_headers)
    assert response.status_code == 404


def test_start_with_base_resume_belonging_to_other_user_returns_404(client, user_with_resume, auth_headers):
    session = SessionLocal()
    other_user = User(email="pipeline-other-pytest@example.com", hashed_password="hashed")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    other_resume = Resume(user_id=other_user.id, structured_content=RESUME_CONTENT, version=1, source="uploaded")
    session.add(other_resume)
    session.commit()
    session.refresh(other_resume)
    other_resume_id, other_user_id = other_resume.id, other_user.id
    session.close()

    try:
        response = client.post(
            "/pipeline/run", json=_base_body(base_resume_id=other_resume_id), headers=auth_headers
        )
        assert response.status_code == 404
    finally:
        session = SessionLocal()
        session.query(Resume).filter(Resume.user_id == other_user_id).delete()
        session.query(User).filter(User.id == other_user_id).delete()
        session.commit()
        session.close()


def test_status_nonexistent_run_returns_404(client, user_with_resume, auth_headers):
    response = client.get("/pipeline/99999999/status", headers=auth_headers)
    assert response.status_code == 404


def test_status_belonging_to_other_user_returns_404(client, user_with_resume, auth_headers):
    session = SessionLocal()
    other_user = User(email="pipeline-status-other-pytest@example.com", hashed_password="hashed")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    other_user_id = other_user.id
    session.close()

    with patch.object(client.app.state.arq_pool, "enqueue_job", new=AsyncMock()):
        start_response = client.post(
            "/pipeline/run",
            json=_base_body(base_resume_id=user_with_resume[1]),
            headers=auth_headers,
        )
    run_id = start_response.json()["run_id"]

    try:
        response = client.get(f"/pipeline/{run_id}/status", headers=auth_headers_for(other_user_id))
        assert response.status_code == 404
    finally:
        session = SessionLocal()
        session.query(User).filter(User.id == other_user_id).delete()
        session.commit()
        session.close()


# --- start: with base_resume_id skips straight to job search ---


def test_start_with_base_resume_id_immediately_queues_job_search(client, user_with_resume, auth_headers):
    user_id, resume_id = user_with_resume

    with patch.object(client.app.state.arq_pool, "enqueue_job", new=AsyncMock()) as mock_enqueue:
        response = client.post(
            "/pipeline/run", json=_base_body(base_resume_id=resume_id), headers=auth_headers
        )

    assert response.status_code == 201
    body = response.json()
    assert body["current_step"] == "SEARCHING_JOBS"
    assert body["resume_id"] == resume_id
    assert body["job_search_run_id"] is not None
    mock_enqueue.assert_awaited_once()

    session = SessionLocal()
    pref = session.query(JobSearchPref).filter(JobSearchPref.user_id == user_id).one()
    assert pref.role == "Backend Engineer"
    session.close()


# --- start: without base_resume_id starts the resume builder ---


def test_start_without_base_resume_id_starts_resume_builder(client, user_with_resume, auth_headers):
    body = _base_body(self_description="I've been a backend engineer for 3 years.")

    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        return_value=AssessmentResult(ready_to_draft=False, clarifying_question="Which company?"),
    ):
        response = client.post("/pipeline/run", json=body, headers=auth_headers)

    assert response.status_code == 201
    resp_body = response.json()
    assert resp_body["current_step"] == "AWAITING_RESUME"
    assert resp_body["resume_builder_run_id"] is not None
    assert "resume-builder" in resp_body["message"]

    session = SessionLocal()
    builder_run = session.get(PipelineRun, resp_body["resume_builder_run_id"])
    assert builder_run.run_type == "resume_builder"
    assert builder_run.current_step == "CLARIFYING"
    session.close()


# --- status: stage transitions via direct sub-run manipulation ---


def test_status_reports_waiting_while_builder_not_finalized(client, user_with_resume, auth_headers):
    user_id, _ = user_with_resume
    session = SessionLocal()
    builder_run = PipelineRun(
        user_id=user_id, run_type="resume_builder", current_step="AWAITING_CONFIRM", status="awaiting_input",
        context={"status": "AWAITING_CONFIRM"},
    )
    session.add(builder_run)
    session.commit()
    session.refresh(builder_run)
    builder_run_id = builder_run.id

    pipeline_run = PipelineRun(
        user_id=user_id, run_type="full_pipeline", current_step="AWAITING_RESUME", status="awaiting_input",
        context={
            "user_id": user_id, "target_field": "Backend Engineer", "emphasis_focus": None,
            "job_search_prefs": {}, "top_n_to_tailor": 1, "resume_id": None,
            "resume_builder_run_id": builder_run_id, "job_search_run_id": None,
            "total_listings_found": None, "shortlist": [], "error": None,
        },
    )
    session.add(pipeline_run)
    session.commit()
    run_id = pipeline_run.id
    session.close()

    response = client.get(f"/pipeline/{run_id}/status", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["current_step"] == "AWAITING_RESUME"
    assert str(builder_run_id) in body["message"]


def test_status_advances_to_searching_jobs_once_builder_finalized(client, user_with_resume, auth_headers):
    user_id, resume_id = user_with_resume
    session = SessionLocal()
    builder_run = PipelineRun(
        user_id=user_id, run_type="resume_builder", current_step="FINALIZED", status="completed",
        context={"status": "FINALIZED", "resume_id": resume_id},
    )
    session.add(builder_run)
    session.commit()
    session.refresh(builder_run)

    pipeline_run = PipelineRun(
        user_id=user_id, run_type="full_pipeline", current_step="AWAITING_RESUME", status="awaiting_input",
        context={
            "user_id": user_id, "target_field": "Backend Engineer", "emphasis_focus": None,
            "job_search_prefs": {"experience_years": None, "location": None, "job_type": None, "work_mode": None},
            "top_n_to_tailor": 1, "resume_id": None,
            "resume_builder_run_id": builder_run.id, "job_search_run_id": None,
            "total_listings_found": None, "shortlist": [], "error": None,
        },
    )
    session.add(pipeline_run)
    session.commit()
    run_id = pipeline_run.id
    session.close()

    with patch.object(client.app.state.arq_pool, "enqueue_job", new=AsyncMock()) as mock_enqueue:
        response = client.get(f"/pipeline/{run_id}/status", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["current_step"] == "SEARCHING_JOBS"
    assert body["resume_id"] == resume_id
    assert body["job_search_run_id"] is not None
    mock_enqueue.assert_awaited_once()


def test_status_marks_pipeline_failed_when_job_search_fails(client, user_with_resume, auth_headers):
    user_id, resume_id = user_with_resume
    session = SessionLocal()
    job_search_run = PipelineRun(
        user_id=user_id, run_type="job_search", current_step="RESULTS_READY", status="failed",
        context={"error": "job search blew up", "ranked_results": []},
    )
    session.add(job_search_run)
    session.commit()
    session.refresh(job_search_run)

    pipeline_run = PipelineRun(
        user_id=user_id, run_type="full_pipeline", current_step="SEARCHING_JOBS", status="in_progress",
        context={
            "user_id": user_id, "target_field": "Backend Engineer", "emphasis_focus": None,
            "job_search_prefs": {}, "top_n_to_tailor": 1, "resume_id": resume_id,
            "resume_builder_run_id": None, "job_search_run_id": job_search_run.id,
            "total_listings_found": None, "shortlist": [], "error": None,
        },
    )
    session.add(pipeline_run)
    session.commit()
    run_id = pipeline_run.id
    session.close()

    response = client.get(f"/pipeline/{run_id}/status", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["current_step"] == "FAILED"
    assert body["error"] == "job search blew up"


# --- status: full shortlist tailoring stage ---


def test_status_builds_tailored_shortlist_once_job_search_completes(client, user_with_resume, auth_headers):
    user_id, resume_id = user_with_resume
    session = SessionLocal()
    listing = JobListing(
        source="test", external_id="pipeline-test-1", title="Django Engineer", company="Acme",
        url="https://example.com/job/1", jd_text="Need a Django engineer with Python skills.",
    )
    session.add(listing)
    session.commit()
    session.refresh(listing)
    listing_db_id = listing.id

    try:
        _assert_shortlist_built_correctly(client, user_id, resume_id, listing, session, auth_headers)
    finally:
        cleanup_session = SessionLocal()
        cleanup_session.query(JobListing).filter(JobListing.id == listing_db_id).delete()
        cleanup_session.commit()
        cleanup_session.close()


def _assert_shortlist_built_correctly(client, user_id, resume_id, listing, session, auth_headers):
    job_search_run = PipelineRun(
        user_id=user_id, run_type="job_search", current_step="RESULTS_READY", status="completed",
        context={
            "total_listings_found": 1,
            "ranked_results": [
                {
                    "listing_id": listing.id, "source": "test", "title": listing.title, "company": listing.company,
                    "url": listing.url, "location": None, "score": 70.0, "must_have_missing": [],
                    "semantic_fit_comment": "Good match.", "min_years_required": None,
                }
            ],
        },
    )
    session.add(job_search_run)
    session.commit()
    session.refresh(job_search_run)

    pipeline_run = PipelineRun(
        user_id=user_id, run_type="full_pipeline", current_step="SEARCHING_JOBS", status="in_progress",
        context={
            "user_id": user_id, "target_field": "Backend Engineer", "emphasis_focus": "Django",
            "job_search_prefs": {}, "top_n_to_tailor": 1, "resume_id": resume_id,
            "resume_builder_run_id": None, "job_search_run_id": job_search_run.id,
            "total_listings_found": None, "shortlist": [], "error": None,
        },
    )
    session.add(pipeline_run)
    session.commit()
    run_id = pipeline_run.id
    listing_id = listing.id
    session.close()

    from app.services.interview_prep import InterviewPrepContent, InterviewQuestion

    terms = JDTerms(must_have=["Python", "Django"], nice_to_have=[])
    tailored_content = ResumeContent(contact=ContactInfo(name="Pipeline Test"), summary="Django-focused engineer.")
    prep_content = InterviewPrepContent(
        questions=[InterviewQuestion(question="Tell me about Django.", why_asked="Core skill.", talking_points=["X"])]
    )

    def dispatch_generate_structured(prompt, schema, temperature=None):
        # llm_client is a single shared singleton across ats_scoring/jd_tailoring_graph/
        # interview_prep — one dispatching mock instead of separate per-module patches, which
        # would silently clobber each other since they all patch the same underlying object.
        if schema is ResumeContent:
            return tailored_content
        if schema is InterviewPrepContent:
            return prep_content
        raise AssertionError(f"Unexpected schema requested in this test: {schema}")

    with (
        # extract_jd_terms is called directly from app.api.pipeline (imported by name there), so
        # patching app.services.ats_scoring.extract_jd_terms would miss this call site.
        patch("app.api.pipeline.extract_jd_terms", return_value=terms),
        patch("app.services.ats_scoring.cosine_similarity", return_value=0.8),
        patch("app.services.ats_scoring.generate_fit_comment", return_value="Strong match."),
        patch("app.services.ats_scoring.extract_candidate_years_experience", return_value=3.0),
        patch("app.services.llm_client.llm_client.generate_structured", side_effect=dispatch_generate_structured),
    ):
        response = client.get(f"/pipeline/{run_id}/status", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["current_step"] == "READY"
    assert body["status"] == "completed"
    assert len(body["shortlist"]) == 1
    item = body["shortlist"][0]
    assert item["listing_id"] == listing_id
    assert item["tailored_resume_id"] is not None
    assert item["tailored_score"] is not None
    assert item["interview_prep_id"] is not None

    session = SessionLocal()
    tailored_resume = session.get(Resume, item["tailored_resume_id"])
    assert tailored_resume.source == "tailored"
    assert tailored_resume.structured_content["summary"] == "Django-focused engineer."
    prep = session.get(InterviewPrep, item["interview_prep_id"])
    assert prep.questions[0]["question"] == "Tell me about Django."
    session.close()
