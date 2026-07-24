from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models import JobSearchPref, PipelineRun, Resume, User


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def resume_with_user():
    session = SessionLocal()
    user = User(email="phase8-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)

    resume = Resume(
        user_id=user.id,
        structured_content={
            "contact": {"name": "Test", "email": "", "phone": "", "location": "", "links": []},
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
    ids = (user.id, resume.id)
    session.close()

    yield ids

    session = SessionLocal()
    session.query(PipelineRun).filter(PipelineRun.user_id == ids[0]).delete()
    session.query(JobSearchPref).filter(JobSearchPref.user_id == ids[0]).delete()
    session.query(Resume).filter(Resume.user_id == ids[0]).delete()
    session.query(User).filter(User.id == ids[0]).delete()
    session.commit()
    session.close()


def test_start_job_search_creates_pref_and_queues_run(client, resume_with_user):
    user_id, resume_id = resume_with_user

    with patch.object(client.app.state.arq_pool, "enqueue_job", new=AsyncMock()) as mock_enqueue:
        response = client.post(
            "/jobs/search",
            json={
                "user_id": user_id,
                "resume_id": resume_id,
                "role": "Backend Engineer",
                "location": "Bangalore",
                "job_type": "full_time",
                "work_mode": "hybrid",
                "experience_years": 1,
                "expected_ctc": "15 LPA+",
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "SEARCH_QUEUED"
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.args[0] == "run_job_search"
    assert mock_enqueue.call_args.args[1] == body["run_id"]

    session = SessionLocal()
    pref = session.query(JobSearchPref).filter(JobSearchPref.user_id == user_id).first()
    assert pref is not None
    assert pref.role == "Backend Engineer"
    run = session.get(PipelineRun, body["run_id"])
    assert run.run_type == "job_search"
    assert run.current_step == "SEARCH_QUEUED"
    session.close()


def test_start_job_search_nonexistent_user_returns_404(client, resume_with_user):
    _, resume_id = resume_with_user
    response = client.post(
        "/jobs/search", json={"user_id": 99999999, "resume_id": resume_id, "role": "Backend Engineer"}
    )
    assert response.status_code == 404


def test_start_job_search_nonexistent_resume_returns_404(client, resume_with_user):
    user_id, _ = resume_with_user
    response = client.post(
        "/jobs/search", json={"user_id": user_id, "resume_id": 99999999, "role": "Backend Engineer"}
    )
    assert response.status_code == 404


def test_get_results_before_ready_returns_empty_results(client, resume_with_user):
    user_id, resume_id = resume_with_user
    session = SessionLocal()
    run = PipelineRun(
        user_id=user_id,
        run_type="job_search",
        current_step="SEARCH_QUEUED",
        status="queued",
        context={"resume_id": resume_id, "role": "Backend Engineer", "ranked_results": []},
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    run_id = run.id
    session.close()

    response = client.get(f"/jobs/search/{run_id}/results")
    assert response.status_code == 200
    body = response.json()
    assert body["current_step"] == "SEARCH_QUEUED"
    assert body["results"] == []


def test_get_results_nonexistent_run_returns_404(client):
    response = client.get("/jobs/search/99999999/results")
    assert response.status_code == 404
