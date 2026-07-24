from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.db import get_db
from app.graphs.resume_builder_graph import BuilderState, resume_builder_graph
from app.models import PipelineRun, Resume, User
from app.schemas.resume import ResumeContent, ResumeContentPatch
from app.schemas.resume_builder import BuilderStateResponse, ConfirmRequest, RespondRequest, StartRequest
from app.services.llm_client import LLMError

router = APIRouter()

RUN_TYPE = "resume_builder"


def _get_run(run_id: int, db: Session) -> PipelineRun:
    run = db.get(PipelineRun, run_id)
    if run is None or run.run_type != RUN_TYPE:
        raise HTTPException(status_code=404, detail=f"Resume builder run {run_id} not found")
    return run


def _persist(run: PipelineRun, state: BuilderState, db: Session) -> None:
    run.context = dict(state)
    # JSONB columns don't auto-detect in-place mutation of the dict they hold; if a caller mutated
    # `run.context` before reassigning it here, SQLAlchemy's dirty-check can see old == new and skip
    # the UPDATE. Force it explicitly so edits always persist.
    flag_modified(run, "context")
    run.current_step = state["status"]
    run.status = "completed" if state["status"] == "FINALIZED" else "awaiting_input"
    db.commit()


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
        raise HTTPException(status_code=502, detail=f"Resume builder LLM call failed: {exc}") from exc


@router.post("/start", response_model=BuilderStateResponse, status_code=status.HTTP_201_CREATED)
def start_resume_builder(body: StartRequest, db: Session = Depends(get_db)) -> BuilderStateResponse:
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {body.user_id} not found")

    base_resume_content = None
    if body.base_resume_id is not None:
        base_resume = db.get(Resume, body.base_resume_id)
        if base_resume is None:
            raise HTTPException(status_code=404, detail=f"Resume {body.base_resume_id} not found")
        if base_resume.user_id != body.user_id:
            raise HTTPException(
                status_code=400, detail=f"Resume {body.base_resume_id} does not belong to user {body.user_id}"
            )
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
    }
    state = _invoke_graph(state)

    run = PipelineRun(
        user_id=body.user_id,
        run_type=RUN_TYPE,
        current_step=state["status"],
        status="completed" if state["status"] == "FINALIZED" else "awaiting_input",
        context=dict(state),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    return _response(run, state)


@router.post("/{run_id}/respond", response_model=BuilderStateResponse)
def respond_to_resume_builder(run_id: int, body: RespondRequest, db: Session = Depends(get_db)) -> BuilderStateResponse:
    run = _get_run(run_id, db)
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
    run_id: int, body: ResumeContentPatch, db: Session = Depends(get_db)
) -> BuilderStateResponse:
    run = _get_run(run_id, db)
    if run.current_step != "AWAITING_CONFIRM":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot patch draft while run is in state '{run.current_step}' (expected AWAITING_CONFIRM)",
        )

    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to patch")

    state: BuilderState = run.context  # type: ignore[assignment]
    merged = {**state["draft"], **updates}
    try:
        ResumeContent.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state["draft"] = merged

    _persist(run, state, db)
    return _response(run, state)


@router.post("/{run_id}/confirm", response_model=BuilderStateResponse)
def confirm_resume_builder(run_id: int, body: ConfirmRequest, db: Session = Depends(get_db)) -> BuilderStateResponse:
    run = _get_run(run_id, db)
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
        state["status"] = "FINALIZED"
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
