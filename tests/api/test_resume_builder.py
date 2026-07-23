from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.graphs.resume_builder_graph import AssessmentResult
from app.main import app
from app.models import PipelineRun, Resume, User
from app.schemas.resume import ContactInfo, ResumeContent

client = TestClient(app)


@pytest.fixture()
def test_user():
    session = SessionLocal()
    user = User(email="phase4-pytest@example.com", hashed_password="hashed")
    session.add(user)
    session.commit()
    session.refresh(user)
    user_id = user.id
    session.close()

    yield user_id

    session = SessionLocal()
    session.query(Resume).filter(Resume.user_id == user_id).delete()
    session.query(PipelineRun).filter(PipelineRun.user_id == user_id).delete()
    session.query(User).filter(User.id == user_id).delete()
    session.commit()
    session.close()


def _llm_side_effect(assess_results, resume_results):
    assess_iter = iter(assess_results)
    resume_iter = iter(resume_results)

    def side_effect(prompt, schema):
        if schema is AssessmentResult:
            return next(assess_iter)
        return next(resume_iter)

    return side_effect


def test_start_returns_clarifying_question_when_info_insufficient(test_user):
    side_effect = _llm_side_effect(
        assess_results=[AssessmentResult(ready_to_draft=False, clarifying_question="What company did you work at?")],
        resume_results=[],
    )
    with patch("app.graphs.resume_builder_graph.llm_client.generate_structured", side_effect=side_effect):
        response = client.post(
            "/resume-builder/start",
            json={"user_id": test_user, "target_field": "Backend Engineer", "self_description": "I did some coding."},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CLARIFYING"
    assert body["clarifying_question"] == "What company did you work at?"
    assert body["draft"] is None
    assert body["resume_id"] is None


def test_full_happy_path_start_respond_confirm(test_user):
    fake_draft = ResumeContent(contact=ContactInfo(name="Test Candidate"), summary="A great engineer.")

    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(
            assess_results=[AssessmentResult(ready_to_draft=False, clarifying_question="Which company?")],
            resume_results=[],
        ),
    ):
        start_response = client.post(
            "/resume-builder/start",
            json={"user_id": test_user, "target_field": "Backend Engineer", "self_description": "I did some coding."},
        )
    run_id = start_response.json()["run_id"]
    assert start_response.json()["status"] == "CLARIFYING"

    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(
            assess_results=[AssessmentResult(ready_to_draft=True)],
            resume_results=[fake_draft],
        ),
    ):
        respond_response = client.post(f"/resume-builder/{run_id}/respond", json={"answer": "Acme Corp, built APIs."})

    assert respond_response.status_code == 200
    respond_body = respond_response.json()
    assert respond_body["status"] == "AWAITING_CONFIRM"
    assert respond_body["draft"]["contact"]["name"] == "Test Candidate"

    confirm_response = client.post(f"/resume-builder/{run_id}/confirm", json={"approved": True})
    assert confirm_response.status_code == 200
    confirm_body = confirm_response.json()
    assert confirm_body["status"] == "FINALIZED"
    assert confirm_body["resume_id"] is not None

    session = SessionLocal()
    stored = session.get(Resume, confirm_body["resume_id"])
    assert stored is not None
    assert stored.structured_content["contact"]["name"] == "Test Candidate"
    session.close()


def test_confirm_revision_loop_preserves_and_updates_draft(test_user):
    initial_draft = ResumeContent(contact=ContactInfo(name=""), summary="Original summary.")
    revised_draft = ResumeContent(contact=ContactInfo(name="Now With Name"), summary="Original summary.")

    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(
            assess_results=[AssessmentResult(ready_to_draft=True)],
            resume_results=[initial_draft],
        ),
    ):
        start_response = client.post(
            "/resume-builder/start",
            json={
                "user_id": test_user,
                "target_field": "Backend Engineer",
                "self_description": "Detailed enough description with concrete facts.",
            },
        )
    run_id = start_response.json()["run_id"]
    assert start_response.json()["status"] == "AWAITING_CONFIRM"

    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(assess_results=[], resume_results=[revised_draft]),
    ):
        revise_response = client.post(
            f"/resume-builder/{run_id}/confirm",
            json={"approved": False, "feedback": "Add my name: Now With Name"},
        )

    assert revise_response.status_code == 200
    body = revise_response.json()
    assert body["status"] == "AWAITING_CONFIRM"
    assert body["draft"]["contact"]["name"] == "Now With Name"
    assert body["draft"]["summary"] == "Original summary."


def test_respond_rejected_when_not_in_clarifying_state(test_user):
    initial_draft = ResumeContent(contact=ContactInfo(name="X"))
    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(
            assess_results=[AssessmentResult(ready_to_draft=True)],
            resume_results=[initial_draft],
        ),
    ):
        start_response = client.post(
            "/resume-builder/start",
            json={"user_id": test_user, "target_field": "Backend Engineer", "self_description": "Enough detail."},
        )
    run_id = start_response.json()["run_id"]

    response = client.post(f"/resume-builder/{run_id}/respond", json={"answer": "irrelevant"})
    assert response.status_code == 409


def test_confirm_requires_feedback_when_rejecting(test_user):
    initial_draft = ResumeContent(contact=ContactInfo(name="X"))
    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(
            assess_results=[AssessmentResult(ready_to_draft=True)],
            resume_results=[initial_draft],
        ),
    ):
        start_response = client.post(
            "/resume-builder/start",
            json={"user_id": test_user, "target_field": "Backend Engineer", "self_description": "Enough detail."},
        )
    run_id = start_response.json()["run_id"]

    response = client.post(f"/resume-builder/{run_id}/confirm", json={"approved": False})
    assert response.status_code == 400


def test_start_with_nonexistent_user_returns_404():
    response = client.post(
        "/resume-builder/start",
        json={"user_id": 99999999, "target_field": "Backend Engineer", "self_description": "whatever"},
    )
    assert response.status_code == 404
