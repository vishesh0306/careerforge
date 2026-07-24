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
