from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.errors import llm_error_response
from app.core.logging import log_transition
from app.core.ownership import get_owned_resume, get_owned_run
from app.graphs.resume_builder_graph import BuilderState, resume_builder_graph
from app.models import PipelineRun, Resume, User
from app.schemas.resume import ResumeContent, ResumeContentPatch, merge_resume_patch
from app.schemas.resume_builder import BuilderStateResponse, ConfirmRequest, RespondRequest, StartRequest
from app.services.llm_client import LLMError

router = APIRouter()

RUN_TYPE = "resume_builder"


def _get_run(run_id: int, current_user: User, db: Session) -> PipelineRun:
    return get_owned_run(run_id, RUN_TYPE, current_user, db)


def _persist(run: PipelineRun, state: BuilderState, db: Session) -> None:
    run.context = dict(state)
    # JSONB columns don't auto-detect in-place mutation of the dict they hold; if a caller mutated
    # `run.context` before reassigning it here, SQLAlchemy's dirty-check can see old == new and skip
    # the UPDATE. Force it explicitly so edits always persist.
    flag_modified(run, "context")
    run.current_step = state["status"]
    run.status = "completed" if state["status"] == "FINALIZED" else "awaiting_input"
    db.commit()
    log_transition(RUN_TYPE, run.id, run.current_step, run.status)


def _response(run: PipelineRun, state: BuilderState, resume_id: int | None = None) -> BuilderStateResponse:
    draft = ResumeContent.model_validate(state["draft"]) if state.get("draft") else None
    return BuilderStateResponse(
        run_id=run.id,
        status=state["status"],
        clarifying_question=state.get("clarifying_question"),
        captured_so_far=state.get("captured_so_far") or [],
        draft=draft,
        resume_id=resume_id,
    )


def _invoke_graph(state: BuilderState) -> BuilderState:
    try:
        return resume_builder_graph.invoke(state)
    except LLMError as exc:
        raise llm_error_response(exc, "Resume builder") from exc


@router.post("/start", response_model=BuilderStateResponse, status_code=status.HTTP_201_CREATED)
def start_resume_builder(
    body: StartRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> BuilderStateResponse:
    base_resume_content = None
    if body.base_resume_id is not None:
        base_resume = get_owned_resume(body.base_resume_id, current_user, db)
        base_resume_content = base_resume.structured_content

    state: BuilderState = {
        "target_field": body.target_field,
        "messages": [{"role": "candidate", "content": body.self_description}],
        "status": "INTAKE",
        "clarifying_question": None,
        "draft": None,
        "revision_feedback": None,
        "entry_point": "assess",
        "base_resume": base_resume_content,
        "base_resume_id": body.base_resume_id,
        "emphasis_focus": body.emphasis_focus,
        "captured_so_far": [],
        "resume_id": None,
    }
    state = _invoke_graph(state)

    run = PipelineRun(
        user_id=current_user.id,
        run_type=RUN_TYPE,
        current_step=state["status"],
        status="completed" if state["status"] == "FINALIZED" else "awaiting_input",
        context=dict(state),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    log_transition(RUN_TYPE, run.id, run.current_step, run.status)

    return _response(run, state)


@router.post("/{run_id}/respond", response_model=BuilderStateResponse)
def respond_to_resume_builder(
    run_id: int,
    body: RespondRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BuilderStateResponse:
    run = _get_run(run_id, current_user, db)
    if run.current_step != "CLARIFYING":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot respond while run is in state '{run.current_step}' (expected CLARIFYING)",
        )

    state: BuilderState = run.context  # type: ignore[assignment]
    state["messages"].append({"role": "candidate", "content": body.answer})
    state["entry_point"] = "assess"
    state = _invoke_graph(state)

    _persist(run, state, db)
    return _response(run, state)


@router.patch("/{run_id}/draft", response_model=BuilderStateResponse)
def patch_resume_builder_draft(
    run_id: int,
    body: ResumeContentPatch,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BuilderStateResponse:
    run = _get_run(run_id, current_user, db)
    if run.current_step != "AWAITING_CONFIRM":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot patch draft while run is in state '{run.current_step}' (expected AWAITING_CONFIRM)",
        )

    if not body.model_fields_set:
        raise HTTPException(status_code=400, detail="No fields provided to patch")

    state: BuilderState = run.context  # type: ignore[assignment]
    merged = merge_resume_patch(state["draft"], body)
    try:
        ResumeContent.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state["draft"] = merged

    _persist(run, state, db)
    return _response(run, state)


@router.post("/{run_id}/confirm", response_model=BuilderStateResponse)
def confirm_resume_builder(
    run_id: int,
    body: ConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BuilderStateResponse:
    run = _get_run(run_id, current_user, db)
    if run.current_step != "AWAITING_CONFIRM":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot confirm while run is in state '{run.current_step}' (expected AWAITING_CONFIRM)",
        )

    state: BuilderState = run.context  # type: ignore[assignment]

    if body.approved:
        base_resume_id = state.get("base_resume_id")
        version = 1
        if base_resume_id is not None:
            base_resume = db.get(Resume, base_resume_id)
            if base_resume is not None:
                version = base_resume.version + 1

        emphasis_focus = state.get("emphasis_focus")
        label = f"Built for {state['target_field']}"
        if emphasis_focus:
            label = f"{label} — {emphasis_focus} focus"

        resume = Resume(
            user_id=run.user_id,
            structured_content=state["draft"],
            version=version,
            source="builder",
            label=label,
            parent_resume_id=base_resume_id,
        )
        db.add(resume)
        db.flush()
        state["status"] = "FINALIZED"
        state["resume_id"] = resume.id
        _persist(run, state, db)
        db.refresh(resume)
        return _response(run, state, resume_id=resume.id)

    if not body.feedback:
        raise HTTPException(status_code=400, detail="feedback is required when approved is false")

    state["revision_feedback"] = body.feedback
    state["entry_point"] = "revise"
    state = _invoke_graph(state)

    _persist(run, state, db)
    return _response(run, state)
