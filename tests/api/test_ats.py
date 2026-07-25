from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models import JDAnalysis, Resume, User
from app.services.ats_scoring import JDTerms
from tests.conftest import auth_headers_for

client = TestClient(app)


@pytest.fixture()
def resume_with_user():
    session = SessionLocal()
    user = User(email="phase6-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)

    resume = Resume(
        user_id=user.id,
        structured_content={
            "contact": {"name": "Test Candidate", "email": "", "phone": "", "location": "", "links": []},
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
    session.query(JDAnalysis).filter(JDAnalysis.resume_id == ids[1]).delete()
    session.query(Resume).filter(Resume.user_id == ids[0]).delete()
    session.query(User).filter(User.id == ids[0]).delete()
    session.commit()
    session.close()


@pytest.fixture()
def auth_headers(resume_with_user):
    user_id, _ = resume_with_user
    return auth_headers_for(user_id)


def test_score_against_jd_stores_analysis_and_returns_breakdown(resume_with_user, auth_headers):
    _, resume_id = resume_with_user
    terms = JDTerms(must_have=["Python", "Kubernetes"], nice_to_have=["Docker"])

    with (
        patch("app.services.ats_scoring.extract_jd_terms", return_value=terms),
        patch("app.services.ats_scoring.cosine_similarity", return_value=0.75),
        patch("app.services.ats_scoring.generate_fit_comment", return_value="Solid Python match, missing Kubernetes."),
    ):
        response = client.post(
            "/ats/score-against-jd",
            json={"resume_id": resume_id, "jd_text": "Need Python and Kubernetes, Docker a plus."},
            headers=auth_headers,
        )

    assert response.status_code == 201
    body = response.json()
    assert body["must_have_present"] == ["Python"]
    assert body["must_have_missing"] == ["Kubernetes"]
    assert body["nice_to_have_missing"] == ["Docker"]
    assert body["semantic_similarity"] == 0.75
    assert body["semantic_fit_comment"] == "Solid Python match, missing Kubernetes."
    assert 0 <= body["score"] <= 100

    session = SessionLocal()
    stored = session.get(JDAnalysis, body["jd_analysis_id"])
    assert stored is not None
    assert stored.resume_id == resume_id
    assert stored.score == body["score"]
    session.close()


def test_score_against_jd_accepts_raw_newlines_in_json_string(resume_with_user, auth_headers):
    # Job descriptions are routinely pasted verbatim, with literal newlines, straight into the
    # jd_text field — that's not valid strict JSON (control chars must be escaped as \n), but
    # rejecting it would 422 every real-world request before our own validation even runs.
    _, resume_id = resume_with_user
    terms = JDTerms(must_have=["Python"], nice_to_have=[])
    raw_body = (
        '{"resume_id": ' + str(resume_id) + ', "jd_text": "Job Summary\nDesign scalable systems\nUse Python daily"}'
    ).encode()

    with (
        patch("app.services.ats_scoring.extract_jd_terms", return_value=terms),
        patch("app.services.ats_scoring.cosine_similarity", return_value=0.8),
        patch("app.services.ats_scoring.generate_fit_comment", return_value="Good fit."),
    ):
        response = client.post(
            "/ats/score-against-jd",
            content=raw_body,
            headers={"Content-Type": "application/json", **auth_headers},
        )

    assert response.status_code == 201
    assert "Design scalable systems" in response.json()["jd_text"]


def test_score_against_jd_penalizes_score_for_experience_gap(resume_with_user, auth_headers):
    _, resume_id = resume_with_user
    session = SessionLocal()
    resume = session.get(Resume, resume_id)
    resume.structured_content = {
        **resume.structured_content,
        "experience": [
            {"company": "Acme", "title": "Engineer", "start_date": "2024-01", "end_date": "Present", "bullets": []}
        ],
    }
    session.commit()
    session.close()

    terms = JDTerms(must_have=["Python"], nice_to_have=[], min_years_required=5.0)

    with (
        patch("app.services.ats_scoring.extract_jd_terms", return_value=terms),
        patch("app.services.ats_scoring.cosine_similarity", return_value=1.0),
        patch("app.services.ats_scoring.extract_candidate_years_experience", return_value=1.0),
        patch("app.services.ats_scoring.generate_fit_comment", return_value="Not enough experience."),
    ):
        response = client.post(
            "/ats/score-against-jd",
            json={"resume_id": resume_id, "jd_text": "Need Python, 5+ years experience."},
            headers=auth_headers,
        )

    assert response.status_code == 201
    body = response.json()
    assert body["candidate_years_experience"] == 1.0
    assert body["min_years_required"] == 5.0
    # Keywords and semantic similarity are perfect (1.0 each), but only 1/5 years covered —
    # the experience component (weight 0.2) must pull the score below a perfect 100.
    assert body["score"] < 100.0


def test_score_against_jd_nonexistent_resume_returns_404(auth_headers):
    response = client.post(
        "/ats/score-against-jd", json={"resume_id": 99999999, "jd_text": "whatever"}, headers=auth_headers
    )
    assert response.status_code == 404


def test_score_against_jd_resume_belonging_to_other_user_returns_404(resume_with_user):
    _, resume_id = resume_with_user
    session = SessionLocal()
    other_user = User(email="phase6-other-pytest@example.com", hashed_password="hashed")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    other_headers = auth_headers_for(other_user.id)
    other_user_id = other_user.id
    session.close()

    try:
        response = client.post(
            "/ats/score-against-jd", json={"resume_id": resume_id, "jd_text": "whatever"}, headers=other_headers
        )
        assert response.status_code == 404
    finally:
        session = SessionLocal()
        session.query(User).filter(User.id == other_user_id).delete()
        session.commit()
        session.close()


def test_score_against_jd_without_auth_returns_403(resume_with_user):
    _, resume_id = resume_with_user
    response = client.post("/ats/score-against-jd", json={"resume_id": resume_id, "jd_text": "whatever"})
    assert response.status_code == 403


def test_score_against_role_synthesizes_jd_then_scores(resume_with_user, auth_headers):
    _, resume_id = resume_with_user
    terms = JDTerms(must_have=["Python"], nice_to_have=[])

    with (
        patch("app.api.ats.synthesize_ideal_jd", return_value="A synthetic backend engineer JD."),
        patch("app.services.ats_scoring.extract_jd_terms", return_value=terms),
        patch("app.services.ats_scoring.cosine_similarity", return_value=0.9),
        patch("app.services.ats_scoring.generate_fit_comment", return_value="Great fit."),
    ):
        response = client.post(
            "/ats/score-against-role",
            json={"resume_id": resume_id, "role": "Backend Engineer", "seniority": "Mid-level"},
            headers=auth_headers,
        )

    assert response.status_code == 201
    body = response.json()
    assert body["jd_text"] == "A synthetic backend engineer JD."
    assert body["must_have_present"] == ["Python"]
    assert body["semantic_similarity"] == 0.9
