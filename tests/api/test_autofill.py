from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models import AutofillDraft, JobListing, Resume, User

client = TestClient(app)


@pytest.fixture()
def resume_and_listing():
    session = SessionLocal()
    user = User(email="phase10-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)

    resume = Resume(
        user_id=user.id,
        structured_content={
            "contact": {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "555-1234",
                "location": "",
                "links": [],
            },
            "summary": "",
            "skills": {"languages": [], "frameworks": [], "tools": [], "cloud_devops": [], "other": []},
            "experience": [],
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

    listing = JobListing(
        source="test",
        external_id="test-1",
        title="Backend Engineer",
        company="Acme",
        url="https://boards.greenhouse.io/acme/jobs/12345",
    )
    session.add(listing)
    session.commit()
    session.refresh(listing)

    ids = (user.id, resume.id, listing.id)
    session.close()

    yield ids

    session = SessionLocal()
    session.query(AutofillDraft).filter(AutofillDraft.job_listing_id == ids[2]).delete()
    session.query(JobListing).filter(JobListing.id == ids[2]).delete()
    session.query(Resume).filter(Resume.user_id == ids[0]).delete()
    session.query(User).filter(User.id == ids[0]).delete()
    session.commit()
    session.close()


def test_create_autofill_draft_stores_result(resume_and_listing):
    _, resume_id, listing_id = resume_and_listing
    fake_result = {
        "ats_platform": "greenhouse",
        "filled_fields": {"First Name": True, "Last Name": True, "Email": True, "Phone": True, "Resume": True},
        "screenshot_base64": "ZmFrZS1wbmctYnl0ZXM=",
    }

    with patch("app.api.autofill.run_autofill_draft", new=AsyncMock(return_value=fake_result)):
        response = client.post(f"/autofill/{listing_id}/draft", json={"resume_id": resume_id})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "filled"
    assert body["ats_platform"] == "greenhouse"
    assert body["submitted"] is False
    assert body["filled_fields"]["Email"] is True
    assert body["screenshot_data_uri"] == "data:image/png;base64,ZmFrZS1wbmctYnl0ZXM="

    session = SessionLocal()
    stored = session.query(AutofillDraft).filter(AutofillDraft.job_listing_id == listing_id).one()
    assert stored.status == "filled"
    assert stored.screenshot_base64 == "ZmFrZS1wbmctYnl0ZXM="
    session.close()


def test_create_autofill_draft_unsupported_platform_returns_400(resume_and_listing):
    _, resume_id, listing_id = resume_and_listing
    session = SessionLocal()
    listing = session.get(JobListing, listing_id)
    listing.url = "https://example.com/careers/123"
    session.commit()
    session.close()

    response = client.post(f"/autofill/{listing_id}/draft", json={"resume_id": resume_id})
    assert response.status_code == 400


def test_create_autofill_draft_nonexistent_listing_returns_404():
    response = client.post("/autofill/99999999/draft", json={"resume_id": 1})
    assert response.status_code == 404


def test_create_autofill_draft_nonexistent_resume_returns_404(resume_and_listing):
    _, _, listing_id = resume_and_listing
    response = client.post(f"/autofill/{listing_id}/draft", json={"resume_id": 99999999})
    assert response.status_code == 404


def test_create_autofill_draft_handles_runner_failure_gracefully(resume_and_listing):
    _, resume_id, listing_id = resume_and_listing

    with patch("app.api.autofill.run_autofill_draft", new=AsyncMock(side_effect=RuntimeError("browser crashed"))):
        response = client.post(f"/autofill/{listing_id}/draft", json={"resume_id": resume_id})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["submitted"] is False
    assert "browser crashed" in body["error"]

    session = SessionLocal()
    stored = session.query(AutofillDraft).filter(AutofillDraft.job_listing_id == listing_id).one()
    assert stored.status == "failed"
    session.close()
