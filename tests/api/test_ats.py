from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models import JDAnalysis, Resume, User
from app.services.ats_scoring import JDTerms

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


def test_score_against_jd_stores_analysis_and_returns_breakdown(resume_with_user):
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


def test_score_against_jd_nonexistent_resume_returns_404():
    response = client.post("/ats/score-against-jd", json={"resume_id": 99999999, "jd_text": "whatever"})
    assert response.status_code == 404


def test_score_against_role_synthesizes_jd_then_scores(resume_with_user):
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
        )

    assert response.status_code == 201
    body = response.json()
    assert body["jd_text"] == "A synthetic backend engineer JD."
    assert body["must_have_present"] == ["Python"]
    assert body["semantic_similarity"] == 0.9
