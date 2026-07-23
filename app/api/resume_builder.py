from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.graphs.resume_builder_graph import BuilderState, resume_builder_graph
from app.models import PipelineRun, Resume, User
from app.schemas.resume import ResumeContent
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
    run.current_step = state["status"]
    run.status = "completed" if state["status"] == "FINALIZED" else "awaiting_input"
    db.commit()


def _response(run: PipelineRun, state: BuilderState, resume_id: int | None = None) -> BuilderStateResponse:
    draft = ResumeContent.model_validate(state["draft"]) if state.get("draft") else None
    return BuilderStateResponse(
        run_id=run.id,
        status=state["status"],
        clarifying_question=state.get("clarifying_question"),
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

    state: BuilderState = {
        "target_field": body.target_field,
        "messages": [{"role": "candidate", "content": body.self_description}],
        "status": "INTAKE",
        "clarifying_question": None,
        "draft": None,
        "revision_feedback": None,
        "entry_point": "assess",
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
        resume = Resume(user_id=run.user_id, structured_content=state["draft"], version=1)
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
