from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models import JDAnalysis, PipelineRun, Resume, User
from app.schemas.resume import ContactInfo, ResumeContent
from app.services.ats_scoring import ATSScoreResult
from tests.conftest import auth_headers_for

client = TestClient(app)

BASE_RESUME = {
    "contact": {"name": "Test Candidate", "email": "", "phone": "", "location": "", "links": []},
    "summary": "",
    "skills": {"languages": ["Python"], "frameworks": [], "tools": [], "cloud_devops": []},
    "experience": [{"company": "Acme", "title": "Engineer", "start_date": "", "end_date": "", "bullets": ["Did a thing."]}],
    "projects": [],
    "education": [],
    "certifications": [],
}

WEAK_SCORE = ATSScoreResult(
    score=50.0,
    must_have_present=["Python"],
    must_have_missing=["Kubernetes"],
    nice_to_have_present=[],
    nice_to_have_missing=[],
    semantic_similarity=0.5,
    semantic_fit_comment="Decent Python base, missing Kubernetes.",
)

STRONG_SCORE = ATSScoreResult(
    score=85.0,
    must_have_present=["Python", "Kubernetes"],
    must_have_missing=[],
    nice_to_have_present=[],
    nice_to_have_missing=[],
    semantic_similarity=0.8,
    semantic_fit_comment="Now a strong match with Kubernetes added.",
)


@pytest.fixture()
def resume_with_user():
    session = SessionLocal()
    user = User(email="phase7-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)

    resume = Resume(user_id=user.id, structured_content=BASE_RESUME, version=1, source="uploaded")
    session.add(resume)
    session.commit()
    session.refresh(resume)
    ids = (user.id, resume.id)
    session.close()

    yield ids

    session = SessionLocal()
    session.query(JDAnalysis).filter(JDAnalysis.resume_id.in_([ids[1], ids[1] + 1])).delete(
        synchronize_session=False
    )
    session.query(PipelineRun).filter(PipelineRun.user_id == ids[0]).delete()
    session.query(Resume).filter(Resume.user_id == ids[0]).delete()
    session.query(User).filter(User.id == ids[0]).delete()
    session.commit()
    session.close()


@pytest.fixture()
def auth_headers(resume_with_user):
    user_id, _ = resume_with_user
    return auth_headers_for(user_id)


def test_start_tailoring_returns_gaps_and_baseline_score(resume_with_user, auth_headers):
    _, resume_id = resume_with_user

    with (
        patch("app.graphs.jd_tailoring_graph.score_resume_against_jd", return_value=WEAK_SCORE),
        patch(
            "app.graphs.jd_tailoring_graph.generate_gap_explanations",
            return_value={"Kubernetes": "The JD requires production Kubernetes experience."},
        ),
    ):
        response = client.post(
            "/tailoring/start", json={"resume_id": resume_id, "jd_text": "Need Kubernetes."}, headers=auth_headers
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "AWAITING_GAP_CONFIRM"
    assert body["original_score"]["score"] == 50.0
    assert body["gaps"] == [
        {
            "term": "Kubernetes",
            "category": "must_have",
            "why_it_matters": "The JD requires production Kubernetes experience.",
            "confirmed": None,
            "detail": None,
        }
    ]
    assert body["tailored_resume_id"] is None

    session = SessionLocal()
    analyses = session.query(JDAnalysis).filter(JDAnalysis.resume_id == resume_id).all()
    assert len(analyses) == 1
    assert analyses[0].score == 50.0
    session.close()


def test_start_tailoring_nonexistent_resume_returns_404(auth_headers):
    response = client.post(
        "/tailoring/start", json={"resume_id": 99999999, "jd_text": "whatever"}, headers=auth_headers
    )
    assert response.status_code == 404


def test_start_tailoring_without_auth_returns_403(resume_with_user):
    _, resume_id = resume_with_user
    response = client.post("/tailoring/start", json={"resume_id": resume_id, "jd_text": "whatever"})
    assert response.status_code == 403


def test_start_tailoring_resume_belonging_to_other_user_returns_404(resume_with_user):
    _, resume_id = resume_with_user
    session = SessionLocal()
    other_user = User(email="phase7-other-pytest@example.com", hashed_password="hashed")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    other_headers = auth_headers_for(other_user.id)
    other_user_id = other_user.id
    session.close()

    try:
        response = client.post(
            "/tailoring/start", json={"resume_id": resume_id, "jd_text": "whatever"}, headers=other_headers
        )
        assert response.status_code == 404
    finally:
        session = SessionLocal()
        session.query(User).filter(User.id == other_user_id).delete()
        session.commit()
        session.close()


def _start_run(resume_id: int, auth_headers: dict) -> int:
    with (
        patch("app.graphs.jd_tailoring_graph.score_resume_against_jd", return_value=WEAK_SCORE),
        patch(
            "app.graphs.jd_tailoring_graph.generate_gap_explanations",
            return_value={"Kubernetes": "The JD requires production Kubernetes experience."},
        ),
    ):
        response = client.post(
            "/tailoring/start", json={"resume_id": resume_id, "jd_text": "Need Kubernetes."}, headers=auth_headers
        )
    return response.json()["run_id"]


def test_confirm_gaps_with_confirmed_gap_creates_new_tailored_resume(resume_with_user, auth_headers):
    _, resume_id = resume_with_user
    run_id = _start_run(resume_id, auth_headers)

    tailored_content = ResumeContent.model_validate(BASE_RESUME)
    tailored_content.skills.tools.append("Kubernetes")

    with (
        patch("app.graphs.jd_tailoring_graph.tailor_resume", return_value=tailored_content) as mock_tailor,
        patch("app.graphs.jd_tailoring_graph.score_resume_against_jd", return_value=STRONG_SCORE),
    ):
        response = client.post(
            "/tailoring/{}/confirm-gaps".format(run_id),
            json={"confirmations": [{"term": "Kubernetes", "confirmed": True, "detail": "Ran a 6-node cluster."}]},
            headers=auth_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RESCORED"
    assert body["tailored_score"]["score"] == 85.0
    assert "Kubernetes" in body["tailored_resume"]["skills"]["tools"]
    assert body["tailored_resume_id"] is not None
    assert body["tailored_resume_id"] != resume_id
    mock_tailor.assert_called_once()

    session = SessionLocal()
    new_resume = session.get(Resume, body["tailored_resume_id"])
    assert new_resume is not None
    assert new_resume.version == 2
    assert new_resume.user_id == session.get(Resume, resume_id).user_id
    assert new_resume.source == "tailored"
    assert new_resume.parent_resume_id == resume_id
    assert new_resume.label == "Tailored resume"
    session.close()


def test_confirm_gaps_all_declined_short_circuits_without_llm_tailor_call(resume_with_user, auth_headers):
    _, resume_id = resume_with_user
    run_id = _start_run(resume_id, auth_headers)

    with patch("app.graphs.jd_tailoring_graph.tailor_resume") as mock_tailor:
        response = client.post(
            "/tailoring/{}/confirm-gaps".format(run_id),
            json={"confirmations": [{"term": "Kubernetes", "confirmed": False}]},
            headers=auth_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["tailored_score"]["score"] == 50.0  # unchanged from original
    assert "Kubernetes" not in body["tailored_resume"]["skills"]["tools"]
    mock_tailor.assert_not_called()


def test_confirm_gaps_emphasis_focus_still_tailors_with_zero_confirmed_gaps(resume_with_user, auth_headers):
    """Critical regression check: a candidate who already has the skill (no gaps to
    confirm) but wants emphasis reordering must still trigger regeneration — this is
    exactly the multi-stack-candidate scenario the emphasis_focus field exists for."""
    _, resume_id = resume_with_user

    with (
        patch("app.graphs.jd_tailoring_graph.score_resume_against_jd", return_value=STRONG_SCORE),
        patch("app.graphs.jd_tailoring_graph.generate_gap_explanations", return_value={}),
    ):
        start_response = client.post(
            "/tailoring/start",
            json={"resume_id": resume_id, "jd_text": "Need Python.", "emphasis_focus": "Django"},
            headers=auth_headers,
        )
    run_id = start_response.json()["run_id"]
    assert start_response.json()["gaps"] == []

    reordered = ResumeContent.model_validate(BASE_RESUME)
    reordered.summary = "Django-focused summary."

    with (
        patch("app.graphs.jd_tailoring_graph.tailor_resume", return_value=reordered) as mock_tailor,
        patch("app.graphs.jd_tailoring_graph.score_resume_against_jd", return_value=STRONG_SCORE),
    ):
        response = client.post(
            f"/tailoring/{run_id}/confirm-gaps", json={"confirmations": []}, headers=auth_headers
        )

    assert response.status_code == 200
    body = response.json()
    mock_tailor.assert_called_once()
    assert mock_tailor.call_args.args[3] == "Django"  # emphasis_focus threaded through
    assert body["tailored_resume"]["summary"] == "Django-focused summary."

    session = SessionLocal()
    new_resume = session.get(Resume, body["tailored_resume_id"])
    assert new_resume.label == "Tailored — Django focus"
    session.close()


def test_confirm_gaps_wrong_state_returns_409(resume_with_user, auth_headers):
    _, resume_id = resume_with_user
    run_id = _start_run(resume_id, auth_headers)

    with patch("app.graphs.jd_tailoring_graph.tailor_resume", return_value=ResumeContent.model_validate(BASE_RESUME)):
        with patch("app.graphs.jd_tailoring_graph.score_resume_against_jd", return_value=STRONG_SCORE):
            client.post(
                "/tailoring/{}/confirm-gaps".format(run_id),
                json={"confirmations": [{"term": "Kubernetes", "confirmed": True}]},
                headers=auth_headers,
            )

    # Second call should now fail — run is already RESCORED.
    response = client.post(
        "/tailoring/{}/confirm-gaps".format(run_id),
        json={"confirmations": [{"term": "Kubernetes", "confirmed": True}]},
        headers=auth_headers,
    )
    assert response.status_code == 409


def test_confirm_gaps_unknown_term_returns_400(resume_with_user, auth_headers):
    _, resume_id = resume_with_user
    run_id = _start_run(resume_id, auth_headers)

    response = client.post(
        "/tailoring/{}/confirm-gaps".format(run_id),
        json={"confirmations": [{"term": "SomethingNotInGapsList", "confirmed": True}]},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_get_result_reflects_persisted_state(resume_with_user, auth_headers):
    _, resume_id = resume_with_user
    run_id = _start_run(resume_id, auth_headers)

    response = client.get(f"/tailoring/{run_id}/result", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "AWAITING_GAP_CONFIRM"
    assert body["run_id"] == run_id


def test_get_result_belonging_to_other_user_returns_404(resume_with_user, auth_headers):
    _, resume_id = resume_with_user
    run_id = _start_run(resume_id, auth_headers)

    session = SessionLocal()
    other_user = User(email="phase7-other-result-pytest@example.com", hashed_password="hashed")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    other_headers = auth_headers_for(other_user.id)
    other_user_id = other_user.id
    session.close()

    try:
        response = client.get(f"/tailoring/{run_id}/result", headers=other_headers)
        assert response.status_code == 404
    finally:
        session = SessionLocal()
        session.query(User).filter(User.id == other_user_id).delete()
        session.commit()
        session.close()
