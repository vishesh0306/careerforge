import pdfplumber
import pytest

from app.core.db import SessionLocal
from app.main import app
from app.models import Resume, User
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture()
def resume_with_user():
    session = SessionLocal()
    user = User(email="phase5-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)

    resume = Resume(
        user_id=user.id,
        structured_content={
            "contact": {
                "name": "Test Candidate",
                "email": "test@example.com",
                "phone": "+91-90000-00000",
                "location": "Bangalore, India",
                "links": ["https://github.com/testcandidate"],
            },
            "summary": "A concise professional summary.",
            "skills": {
                "languages": ["Python"],
                "frameworks": ["FastAPI"],
                "tools": [],
                "cloud_devops": [],
            },
            "experience": [
                {
                    "company": "Acme Corp",
                    "title": "Backend Engineer",
                    "start_date": "Jan 2022",
                    "end_date": "Present",
                    "bullets": ["Did a thing that mattered."],
                }
            ],
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
    session.query(Resume).filter(Resume.user_id == ids[0]).delete()
    session.query(User).filter(User.id == ids[0]).delete()
    session.commit()
    session.close()


def test_download_pdf_returns_valid_pdf_with_extractable_text(resume_with_user, tmp_path):
    _, resume_id = resume_with_user
    response = client.get(f"/resumes/{resume_id}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"

    pdf_path = tmp_path / "out.pdf"
    pdf_path.write_bytes(response.content)
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    assert "Test Candidate" in text
    assert "Acme Corp" in text
    assert "Did a thing that mattered." in text


def test_download_pdf_for_nonexistent_resume_returns_404():
    response = client.get("/resumes/99999999/pdf")
    assert response.status_code == 404


def test_download_pdf_handles_missing_optional_sections(resume_with_user):
    _, resume_id = resume_with_user
    response = client.get(f"/resumes/{resume_id}/pdf")
    assert response.status_code == 200
    assert response.content[:4] == b"%PDF"
