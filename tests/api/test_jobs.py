from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models import JobSearchPref, PipelineRun, Resume, User
from tests.conftest import auth_headers_for


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
        source="uploaded",
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


@pytest.fixture()
def auth_headers(resume_with_user):
    user_id, _ = resume_with_user
    return auth_headers_for(user_id)


def test_start_job_search_creates_pref_and_queues_run(client, resume_with_user, auth_headers):
    user_id, resume_id = resume_with_user

    with patch.object(client.app.state.arq_pool, "enqueue_job", new=AsyncMock()) as mock_enqueue:
        response = client.post(
            "/jobs/search",
            json={
                "resume_id": resume_id,
                "role": "Backend Engineer",
                "location": "Bangalore",
                "job_type": "full_time",
                "work_mode": "hybrid",
                "experience_years": 1,
                "expected_ctc": "15 LPA+",
            },
            headers=auth_headers,
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


def test_start_job_search_without_auth_returns_403(client, resume_with_user):
    _, resume_id = resume_with_user
    response = client.post("/jobs/search", json={"resume_id": resume_id, "role": "Backend Engineer"})
    assert response.status_code == 403


def test_start_job_search_nonexistent_resume_returns_404(client, auth_headers):
    response = client.post(
        "/jobs/search", json={"resume_id": 99999999, "role": "Backend Engineer"}, headers=auth_headers
    )
    assert response.status_code == 404


def test_start_job_search_resume_belonging_to_other_user_returns_404(client, resume_with_user):
    _, resume_id = resume_with_user
    session = SessionLocal()
    other_user = User(email="phase8-other-pytest@example.com", hashed_password="hashed")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    other_headers = auth_headers_for(other_user.id)
    other_user_id = other_user.id
    session.close()

    try:
        response = client.post(
            "/jobs/search", json={"resume_id": resume_id, "role": "Backend Engineer"}, headers=other_headers
        )
        assert response.status_code == 404
    finally:
        session = SessionLocal()
        session.query(User).filter(User.id == other_user_id).delete()
        session.commit()
        session.close()


def test_get_results_before_ready_returns_empty_results(client, resume_with_user, auth_headers):
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

    response = client.get(f"/jobs/search/{run_id}/results", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["current_step"] == "SEARCH_QUEUED"
    assert body["results"] == []


def test_get_results_nonexistent_run_returns_404(client, auth_headers):
    response = client.get("/jobs/search/99999999/results", headers=auth_headers)
    assert response.status_code == 404


def test_get_results_belonging_to_other_user_returns_404(client, resume_with_user):
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

    other_user = User(email="phase8-other-results-pytest@example.com", hashed_password="hashed")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    other_headers = auth_headers_for(other_user.id)
    other_user_id = other_user.id
    session.close()

    try:
        response = client.get(f"/jobs/search/{run_id}/results", headers=other_headers)
        assert response.status_code == 404
    finally:
        session = SessionLocal()
        session.query(User).filter(User.id == other_user_id).delete()
        session.commit()
        session.close()
