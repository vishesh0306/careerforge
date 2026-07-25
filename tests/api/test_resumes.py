import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models import Resume, User
from app.schemas.resume import ContactInfo, ResumeContent

client = TestClient(app)


@pytest.fixture()
def test_user():
    session = SessionLocal()
    user = User(email="phase3-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)
    user_id = user.id
    session.close()

    yield user_id

    session = SessionLocal()
    session.query(Resume).filter(Resume.user_id == user_id).delete()
    session.query(User).filter(User.id == user_id).delete()
    session.commit()
    session.close()


def test_upload_unsupported_file_type(test_user):
    response = client.post(
        f"/resumes/upload?user_id={test_user}",
        files={"file": ("resume.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_upload_empty_file(test_user):
    response = client.post(
        f"/resumes/upload?user_id={test_user}",
        files={"file": ("resume.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_upload_corrupted_pdf(test_user):
    response = client.post(
        f"/resumes/upload?user_id={test_user}",
        files={"file": ("resume.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")},
    )
    assert response.status_code == 400


def test_upload_nonexistent_user():
    response = client.post(
        "/resumes/upload?user_id=99999999",
        files={"file": ("resume.pdf", io.BytesIO(b"whatever"), "application/pdf")},
    )
    assert response.status_code == 404


def test_upload_valid_docx_stores_structured_resume(test_user):
    fake_content = ResumeContent(contact=ContactInfo(name="Test Person", email="test@example.com"))

    with patch("app.services.resume_parser.llm_client.generate_structured", return_value=fake_content):
        with open("tests/fixtures/sample_resume.docx", "rb") as f:
            response = client.post(
                f"/resumes/upload?user_id={test_user}",
                files={
                    "file": (
                        "resume.docx",
                        f,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == test_user
    assert body["structured_content"]["contact"]["name"] == "Test Person"
    assert body["version"] == 1
    assert body["source"] == "uploaded"
    assert body["label"] == "Uploaded resume"
    assert body["parent_resume_id"] is None


def test_upload_returns_503_not_400_when_gemini_quota_exhausted(test_user):
    # Quota exhaustion is an AI-service availability problem, not a problem with the candidate's
    # file — it must not be misreported as a 400 Bad Request (ResumeParsingError's status code).
    from app.services.llm_client import LLMQuotaExhaustedError

    quota_error = LLMQuotaExhaustedError("All 2 configured Gemini API key(s) are currently rate-limited.")
    with patch("app.services.resume_parser.llm_client.generate_structured", side_effect=quota_error):
        with open("tests/fixtures/sample_resume.docx", "rb") as f:
            response = client.post(
                f"/resumes/upload?user_id={test_user}",
                files={
                    "file": (
                        "resume.docx",
                        f,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_list_resumes_returns_all_resumes_for_user(test_user):
    fake_content = ResumeContent(contact=ContactInfo(name="Test Person"))

    with patch("app.services.resume_parser.llm_client.generate_structured", return_value=fake_content):
        with open("tests/fixtures/sample_resume.docx", "rb") as f:
            client.post(
                f"/resumes/upload?user_id={test_user}",
                files={
                    "file": (
                        "resume.docx",
                        f,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )

    response = client.get(f"/resumes?user_id={test_user}")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["source"] == "uploaded"


def test_list_resumes_nonexistent_user_returns_404():
    response = client.get("/resumes?user_id=99999999")
    assert response.status_code == 404


def test_list_resumes_empty_for_user_with_no_resumes(test_user):
    response = client.get(f"/resumes?user_id={test_user}")
    assert response.status_code == 200
    assert response.json() == []


def test_patch_resume_replaces_only_included_sections(test_user):
    session = SessionLocal()
    resume = Resume(
        user_id=test_user,
        structured_content={
            "contact": {"name": "Original Name", "email": "orig@example.com", "phone": "", "location": "", "links": []},
            "summary": "Original summary.",
            "skills": {"languages": ["Python"], "frameworks": [], "tools": [], "cloud_devops": []},
            "experience": [],
            "projects": [],
            "education": [],
            "certifications": ["AWS Certified"],
        },
        version=1,
        source="uploaded",
    )
    session.add(resume)
    session.commit()
    session.refresh(resume)
    resume_id = resume.id
    session.close()

    response = client.patch(f"/resumes/{resume_id}", json={"summary": "Patched summary."})

    assert response.status_code == 200
    body = response.json()
    assert body["structured_content"]["summary"] == "Patched summary."
    assert body["structured_content"]["contact"]["name"] == "Original Name"
    assert body["structured_content"]["certifications"] == ["AWS Certified"]


def test_patch_resume_certifications_are_appended_not_replaced(test_user):
    session = SessionLocal()
    resume = Resume(
        user_id=test_user,
        structured_content={
            "contact": {"name": "X", "email": "", "phone": "", "location": "", "links": []},
            "summary": "",
            "skills": {"languages": [], "frameworks": [], "tools": [], "cloud_devops": []},
            "experience": [],
            "projects": [],
            "education": [],
            "certifications": ["AWS Certified"],
        },
        version=1,
        source="uploaded",
    )
    session.add(resume)
    session.commit()
    session.refresh(resume)
    resume_id = resume.id
    session.close()

    response = client.patch(f"/resumes/{resume_id}", json={"certifications": ["CKA", "AWS Certified"]})

    assert response.status_code == 200
    # "AWS Certified" already existed — appended list should skip the exact duplicate.
    assert response.json()["structured_content"]["certifications"] == ["AWS Certified", "CKA"]


def test_patch_resume_skills_sublist_is_appended_not_replaced(test_user):
    session = SessionLocal()
    resume = Resume(
        user_id=test_user,
        structured_content={
            "contact": {"name": "X", "email": "", "phone": "", "location": "", "links": []},
            "summary": "",
            "skills": {"languages": ["Python"], "frameworks": ["Django"], "tools": [], "cloud_devops": []},
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
    resume_id = resume.id
    session.close()

    response = client.patch(f"/resumes/{resume_id}", json={"skills": {"languages": ["English"]}})

    assert response.status_code == 200
    skills = response.json()["structured_content"]["skills"]
    assert skills["languages"] == ["Python", "English"]
    assert skills["frameworks"] == ["Django"]  # untouched sub-list preserved


def test_patch_resume_contact_partial_update_preserves_other_fields(test_user):
    session = SessionLocal()
    resume = Resume(
        user_id=test_user,
        structured_content={
            "contact": {
                "name": "Original Name",
                "email": "old@example.com",
                "phone": "555-1234",
                "location": "Remote",
                "links": ["https://github.com/orig"],
            },
            "summary": "",
            "skills": {"languages": [], "frameworks": [], "tools": [], "cloud_devops": []},
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
    resume_id = resume.id
    session.close()

    response = client.patch(f"/resumes/{resume_id}", json={"contact": {"email": "new@example.com"}})

    assert response.status_code == 200
    contact = response.json()["structured_content"]["contact"]
    assert contact["email"] == "new@example.com"
    assert contact["name"] == "Original Name"
    assert contact["phone"] == "555-1234"
    assert contact["links"] == ["https://github.com/orig"]


def test_patch_resume_experience_entries_are_appended_not_replaced(test_user):
    session = SessionLocal()
    resume = Resume(
        user_id=test_user,
        structured_content={
            "contact": {"name": "X", "email": "", "phone": "", "location": "", "links": []},
            "summary": "",
            "skills": {"languages": [], "frameworks": [], "tools": [], "cloud_devops": []},
            "experience": [{"company": "Acme", "title": "Engineer", "start_date": "", "end_date": "", "bullets": []}],
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
    resume_id = resume.id
    session.close()

    response = client.patch(
        f"/resumes/{resume_id}",
        json={"experience": [{"company": "NewCo", "title": "Senior Engineer", "bullets": ["Did stuff"]}]},
    )

    assert response.status_code == 200
    experience = response.json()["structured_content"]["experience"]
    assert len(experience) == 2
    assert experience[0]["company"] == "Acme"
    assert experience[1]["company"] == "NewCo"


def test_patch_resume_nonexistent_returns_404(test_user):
    response = client.patch("/resumes/99999999", json={"summary": "New summary."})
    assert response.status_code == 404


def test_patch_resume_empty_body_returns_400(test_user):
    session = SessionLocal()
    resume = Resume(
        user_id=test_user,
        structured_content={"contact": {"name": "X", "email": "", "phone": "", "location": "", "links": []}},
        version=1,
        source="uploaded",
    )
    session.add(resume)
    session.commit()
    session.refresh(resume)
    resume_id = resume.id
    session.close()

    response = client.patch(f"/resumes/{resume_id}", json={})
    assert response.status_code == 400
