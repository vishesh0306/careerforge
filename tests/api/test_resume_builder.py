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
    assert stored.source == "builder"
    assert stored.label == "Built for Backend Engineer"
    assert stored.parent_resume_id is None
    session.close()


def test_start_with_nonexistent_base_resume_returns_404(test_user):
    response = client.post(
        "/resume-builder/start",
        json={
            "user_id": test_user,
            "target_field": "Backend Engineer",
            "self_description": "Add my new role.",
            "base_resume_id": 99999999,
        },
    )
    assert response.status_code == 404


def test_start_with_base_resume_belonging_to_other_user_returns_400(test_user):
    session = SessionLocal()
    other_user = User(email="other-owner-pytest@example.com", hashed_password="hashed")
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    other_resume = Resume(
        user_id=other_user.id, structured_content={"contact": {"name": "Other"}}, version=1, source="uploaded"
    )
    session.add(other_resume)
    session.commit()
    session.refresh(other_resume)
    other_resume_id, other_user_id = other_resume.id, other_user.id
    session.close()

    try:
        response = client.post(
            "/resume-builder/start",
            json={
                "user_id": test_user,
                "target_field": "Backend Engineer",
                "self_description": "Add my new role.",
                "base_resume_id": other_resume_id,
            },
        )
        assert response.status_code == 400
    finally:
        session = SessionLocal()
        session.query(Resume).filter(Resume.user_id == other_user_id).delete()
        session.query(User).filter(User.id == other_user_id).delete()
        session.commit()
        session.close()


def test_build_from_base_resume_seeds_context_and_sets_lineage_on_finalize(test_user):
    session = SessionLocal()
    base = Resume(
        user_id=test_user,
        structured_content={
            "contact": {"name": "Original Name", "email": "", "phone": "", "location": "", "links": []},
            "summary": "Old summary.",
            "skills": {"languages": ["Python"], "frameworks": [], "tools": [], "cloud_devops": []},
            "experience": [],
            "projects": [],
            "education": [],
            "certifications": [],
        },
        version=1,
        source="uploaded",
    )
    session.add(base)
    session.commit()
    session.refresh(base)
    base_id = base.id
    session.close()

    updated_draft = ResumeContent(
        contact=ContactInfo(name="Original Name"), summary="Updated summary with new role."
    )

    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(
            assess_results=[AssessmentResult(ready_to_draft=True)],
            resume_results=[updated_draft],
        ),
    ) as mock_llm:
        start_response = client.post(
            "/resume-builder/start",
            json={
                "user_id": test_user,
                "target_field": "Backend Engineer",
                "self_description": "I got promoted, add my new title and a new achievement.",
                "base_resume_id": base_id,
            },
        )

    assert start_response.status_code == 201
    body = start_response.json()
    assert body["status"] == "AWAITING_CONFIRM"
    assert body["draft"]["summary"] == "Updated summary with new role."

    # The draft call must have used the base-resume-aware prompt, not the from-scratch one.
    draft_call_prompt = mock_llm.call_args_list[-1].args[0]
    assert "Original Name" in draft_call_prompt
    assert "updating a candidate's EXISTING resume" in draft_call_prompt

    run_id = body["run_id"]
    confirm_response = client.post(f"/resume-builder/{run_id}/confirm", json={"approved": True})
    assert confirm_response.status_code == 200
    confirm_body = confirm_response.json()

    session = SessionLocal()
    new_resume = session.get(Resume, confirm_body["resume_id"])
    assert new_resume.parent_resume_id == base_id
    assert new_resume.version == 2  # base resume was version 1
    session.close()


def test_captured_so_far_surfaced_during_clarifying(test_user):
    side_effect = _llm_side_effect(
        assess_results=[
            AssessmentResult(
                ready_to_draft=False,
                clarifying_question="What company did you work at?",
                captured_so_far=["Backend engineer", "Worked on APIs"],
            )
        ],
        resume_results=[],
    )
    with patch("app.graphs.resume_builder_graph.llm_client.generate_structured", side_effect=side_effect):
        response = client.post(
            "/resume-builder/start",
            json={"user_id": test_user, "target_field": "Backend Engineer", "self_description": "I did some coding."},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["captured_so_far"] == ["Backend engineer", "Worked on APIs"]


def test_captured_so_far_defaults_to_empty_list_when_not_returned(test_user):
    side_effect = _llm_side_effect(
        assess_results=[AssessmentResult(ready_to_draft=False, clarifying_question="What company?")],
        resume_results=[],
    )
    with patch("app.graphs.resume_builder_graph.llm_client.generate_structured", side_effect=side_effect):
        response = client.post(
            "/resume-builder/start",
            json={"user_id": test_user, "target_field": "Backend Engineer", "self_description": "I did some coding."},
        )

    assert response.status_code == 201
    assert response.json()["captured_so_far"] == []


def test_start_with_emphasis_focus_steers_clarifying_question(test_user):
    side_effect = _llm_side_effect(
        assess_results=[AssessmentResult(ready_to_draft=False, clarifying_question="Tell me more about Django.")],
        resume_results=[],
    )
    with patch("app.graphs.resume_builder_graph.llm_client.generate_structured", side_effect=side_effect) as mock_llm:
        response = client.post(
            "/resume-builder/start",
            json={
                "user_id": test_user,
                "target_field": "Backend Engineer",
                "self_description": "I know Django and Spring Boot.",
                "emphasis_focus": "Django",
            },
        )

    assert response.status_code == 201
    assess_prompt = mock_llm.call_args_list[0].args[0]
    assert 'foreground their "Django" experience' in assess_prompt


def test_confirm_with_emphasis_focus_sets_label_and_uses_emphasis_instructions(test_user):
    fake_draft = ResumeContent(contact=ContactInfo(name="Test Candidate"), summary="A great Django engineer.")

    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(
            assess_results=[AssessmentResult(ready_to_draft=True)],
            resume_results=[fake_draft],
        ),
    ) as mock_llm:
        start_response = client.post(
            "/resume-builder/start",
            json={
                "user_id": test_user,
                "target_field": "Backend Engineer",
                "self_description": "I know Django and Spring Boot, built APIs with both.",
                "emphasis_focus": "Django",
            },
        )

    assert start_response.status_code == 201
    draft_prompt = mock_llm.call_args_list[-1].args[0]
    assert 'foreground their "Django" experience' in draft_prompt
    assert "Do NOT omit or delete" in draft_prompt

    run_id = start_response.json()["run_id"]
    confirm_response = client.post(f"/resume-builder/{run_id}/confirm", json={"approved": True})
    assert confirm_response.status_code == 200
    resume_id = confirm_response.json()["resume_id"]

    session = SessionLocal()
    stored = session.get(Resume, resume_id)
    assert stored.label == "Built for Backend Engineer — Django focus"
    session.close()


def test_patch_draft_replaces_only_included_sections(test_user):
    fake_draft = ResumeContent(
        contact=ContactInfo(name="Test Candidate"), summary="A great engineer.", certifications=["AWS Certified"]
    )

    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(assess_results=[AssessmentResult(ready_to_draft=True)], resume_results=[fake_draft]),
    ):
        start_response = client.post(
            "/resume-builder/start",
            json={"user_id": test_user, "target_field": "Backend Engineer", "self_description": "Enough detail."},
        )
    run_id = start_response.json()["run_id"]

    patch_response = client.patch(f"/resume-builder/{run_id}/draft", json={"summary": "Manually edited summary."})

    assert patch_response.status_code == 200
    body = patch_response.json()
    assert body["draft"]["summary"] == "Manually edited summary."
    assert body["draft"]["contact"]["name"] == "Test Candidate"
    assert body["draft"]["certifications"] == ["AWS Certified"]
    assert body["status"] == "AWAITING_CONFIRM"

    confirm_response = client.post(f"/resume-builder/{run_id}/confirm", json={"approved": True})
    assert confirm_response.status_code == 200
    resume_id = confirm_response.json()["resume_id"]

    session = SessionLocal()
    stored = session.get(Resume, resume_id)
    assert stored.structured_content["summary"] == "Manually edited summary."
    session.close()


def test_patch_draft_rejected_when_not_awaiting_confirm(test_user):
    side_effect = _llm_side_effect(
        assess_results=[AssessmentResult(ready_to_draft=False, clarifying_question="Which company?")],
        resume_results=[],
    )
    with patch("app.graphs.resume_builder_graph.llm_client.generate_structured", side_effect=side_effect):
        start_response = client.post(
            "/resume-builder/start",
            json={"user_id": test_user, "target_field": "Backend Engineer", "self_description": "I did some coding."},
        )
    run_id = start_response.json()["run_id"]

    response = client.patch(f"/resume-builder/{run_id}/draft", json={"summary": "New summary."})
    assert response.status_code == 409


def test_patch_draft_empty_body_returns_400(test_user):
    initial_draft = ResumeContent(contact=ContactInfo(name="X"))
    with patch(
        "app.graphs.resume_builder_graph.llm_client.generate_structured",
        side_effect=_llm_side_effect(assess_results=[AssessmentResult(ready_to_draft=True)], resume_results=[initial_draft]),
    ):
        start_response = client.post(
            "/resume-builder/start",
            json={"user_id": test_user, "target_field": "Backend Engineer", "self_description": "Enough detail."},
        )
    run_id = start_response.json()["run_id"]

    response = client.patch(f"/resume-builder/{run_id}/draft", json={})
    assert response.status_code == 400


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
