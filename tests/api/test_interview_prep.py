from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models import InterviewPrep, JDAnalysis, Resume, User
from app.services.interview_prep import InterviewPrepContent, InterviewQuestion
from tests.conftest import auth_headers_for

client = TestClient(app)


@pytest.fixture()
def jd_analysis_with_resume():
    session = SessionLocal()
    user = User(email="phase9-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)

    resume = Resume(
        user_id=user.id,
        structured_content={
            "contact": {"name": "Test Candidate", "email": "", "phone": "", "location": "", "links": []},
            "summary": "",
            "skills": {
                "languages": ["Python"],
                "frameworks": ["Django"],
                "tools": [],
                "cloud_devops": [],
                "other": [],
            },
            "experience": [
                {
                    "company": "Acme",
                    "title": "Backend Engineer",
                    "start_date": "2022-01",
                    "end_date": "Present",
                    "bullets": ["Built APIs."],
                }
            ],
            "projects": [],
            "education": [],
            "certifications": [],
            "achievements": [],
        },
        version=1,
        source="uploaded",
    )
    session.add(resume)
    session.commit()
    session.refresh(resume)

    analysis = JDAnalysis(
        resume_id=resume.id,
        jd_text="Need a Python/Django backend engineer with Kubernetes experience.",
        score=70.0,
        breakdown={
            "must_have_present": ["Python", "Django"],
            "must_have_missing": ["Kubernetes"],
            "nice_to_have_present": [],
            "nice_to_have_missing": [],
            "semantic_similarity": 0.7,
            "semantic_fit_comment": "Strong Python/Django match, missing Kubernetes.",
            "min_years_required": 3.0,
            "candidate_years_experience": 2.0,
        },
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)

    ids = (user.id, resume.id, analysis.id)
    session.close()

    yield ids

    session = SessionLocal()
    session.query(InterviewPrep).filter(InterviewPrep.jd_analysis_id == ids[2]).delete()
    session.query(JDAnalysis).filter(JDAnalysis.id == ids[2]).delete()
    session.query(Resume).filter(Resume.user_id == ids[0]).delete()
    session.query(User).filter(User.id == ids[0]).delete()
    session.commit()
    session.close()


def test_generate_prep_stores_and_returns_questions(jd_analysis_with_resume):
    user_id, _, analysis_id = jd_analysis_with_resume
    fake_result = InterviewPrepContent(
        questions=[
            InterviewQuestion(
                question="We noticed you haven't used Kubernetes — how would you approach learning it?",
                why_asked="Kubernetes is a missing must-have requirement for this role.",
                talking_points=["Mention Docker experience as a stepping stone", "Show willingness to learn"],
            )
        ]
    )

    with patch("app.services.interview_prep.llm_client.generate_structured", return_value=fake_result):
        response = client.post(f"/interview-prep/{analysis_id}", headers=auth_headers_for(user_id))

    assert response.status_code == 201
    body = response.json()
    assert body["jd_analysis_id"] == analysis_id
    assert len(body["questions"]) == 1
    assert "Kubernetes" in body["questions"][0]["question"]
    assert body["questions"][0]["talking_points"] == [
        "Mention Docker experience as a stepping stone",
        "Show willingness to learn",
    ]

    session = SessionLocal()
    stored = session.query(InterviewPrep).filter(InterviewPrep.jd_analysis_id == analysis_id).one()
    assert len(stored.questions) == 1
    assert stored.questions[0]["question"] == fake_result.questions[0].question
    session.close()


def test_generate_prep_prompt_includes_gap_specifics(jd_analysis_with_resume):
    user_id, _, analysis_id = jd_analysis_with_resume
    fake_result = InterviewPrepContent(
        questions=[InterviewQuestion(question="Q", why_asked="W", talking_points=["T"])]
    )

    with patch("app.services.interview_prep.llm_client.generate_structured", return_value=fake_result) as mock_llm:
        client.post(f"/interview-prep/{analysis_id}", headers=auth_headers_for(user_id))

    prompt = mock_llm.call_args.args[0]
    assert "Kubernetes" in prompt
    assert "Acme" in prompt
    assert "3.0" in prompt
    assert "2.0" in prompt


def test_generate_prep_nonexistent_jd_analysis_returns_404(jd_analysis_with_resume):
    user_id, _, _ = jd_analysis_with_resume
    response = client.post("/interview-prep/99999999", headers=auth_headers_for(user_id))
    assert response.status_code == 404


def test_generate_prep_without_auth_returns_403(jd_analysis_with_resume):
    _, _, analysis_id = jd_analysis_with_resume
    response = client.post(f"/interview-prep/{analysis_id}")
    assert response.status_code == 403


def test_generate_prep_belonging_to_other_user_returns_404(jd_analysis_with_resume):
    _, _, analysis_id = jd_analysis_with_resume
    session = SessionLocal()
    other_user = User(email="phase9-other-pytest@example.com", hashed_password="hashed")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    other_headers = auth_headers_for(other_user.id)
    other_user_id = other_user.id
    session.close()

    try:
        response = client.post(f"/interview-prep/{analysis_id}", headers=other_headers)
        assert response.status_code == 404
    finally:
        session = SessionLocal()
        session.query(User).filter(User.id == other_user_id).delete()
        session.commit()
        session.close()
