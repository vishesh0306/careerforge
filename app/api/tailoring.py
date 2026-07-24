from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.graphs.jd_tailoring_graph import TailoringState, jd_tailoring_graph
from app.models import JDAnalysis, PipelineRun, Resume
from app.schemas.resume import ResumeContent
from app.schemas.tailoring import ConfirmGapsRequest, TailoringStartRequest, TailoringStateResponse
from app.services.llm_client import LLMError

router = APIRouter()

RUN_TYPE = "jd_tailoring"


def _get_run(run_id: int, db: Session) -> PipelineRun:
    run = db.get(PipelineRun, run_id)
    if run is None or run.run_type != RUN_TYPE:
        raise HTTPException(status_code=404, detail=f"Tailoring run {run_id} not found")
    return run


def _invoke_graph(state: TailoringState) -> TailoringState:
    try:
        return jd_tailoring_graph.invoke(state)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"Tailoring LLM call failed: {exc}") from exc


def _response(run: PipelineRun, state: TailoringState) -> TailoringStateResponse:
    return TailoringStateResponse(
        run_id=run.id,
        status=state["status"],
        jd_text=state["jd_text"],
        original_score=state["original_score"],
        gaps=state["gaps"],
        tailored_resume_id=state.get("tailored_resume_id"),
        tailored_resume=state["tailored_resume"] if state.get("tailored_resume") else None,
        tailored_score=state["tailored_score"] if state.get("tailored_score") else None,
    )


@router.post("/start", response_model=TailoringStateResponse, status_code=status.HTTP_201_CREATED)
def start_tailoring(body: TailoringStartRequest, db: Session = Depends(get_db)) -> TailoringStateResponse:
    resume = db.get(Resume, body.resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail=f"Resume {body.resume_id} not found")

    state: TailoringState = {
        "resume_id": resume.id,
        "jd_text": body.jd_text,
        "original_resume": resume.structured_content,
        "original_score": {},
        "gaps": [],
        "tailored_resume": None,
        "tailored_score": None,
        "status": "AWAITING_GAP_CONFIRM",
        "entry_point": "score_and_review",
    }
    state = _invoke_graph(state)

    run = PipelineRun(
        user_id=resume.user_id,
        run_type=RUN_TYPE,
        current_step=state["status"],
        status="awaiting_input",
        context=dict(state),
    )
    db.add(run)

    # Persist the baseline score for audit/before-after comparison.
    db.add(
        JDAnalysis(
            resume_id=resume.id,
            jd_text=body.jd_text,
            score=state["original_score"]["score"],
            breakdown=state["original_score"],
        )
    )
    db.commit()
    db.refresh(run)

    return _response(run, state)


@router.post("/{run_id}/confirm-gaps", response_model=TailoringStateResponse)
def confirm_gaps(run_id: int, body: ConfirmGapsRequest, db: Session = Depends(get_db)) -> TailoringStateResponse:
    run = _get_run(run_id, db)
    if run.current_step != "AWAITING_GAP_CONFIRM":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot confirm gaps while run is in state '{run.current_step}' (expected AWAITING_GAP_CONFIRM)",
        )

    state: TailoringState = run.context  # type: ignore[assignment]
    confirmations_by_term = {c.term: c for c in body.confirmations}

    known_terms = {gap["term"] for gap in state["gaps"]}
    unknown = set(confirmations_by_term) - known_terms
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown gap term(s): {sorted(unknown)}")

    for gap in state["gaps"]:
        confirmation = confirmations_by_term.get(gap["term"])
        if confirmation is not None:
            gap["confirmed"] = confirmation.confirmed
            gap["detail"] = confirmation.detail
        else:
            # No explicit answer for this gap — treat as declined. Never add anything
            # the user hasn't explicitly confirmed.
            gap["confirmed"] = False
            gap["detail"] = None

    state["entry_point"] = "tailor_and_rescore"
    state = _invoke_graph(state)

    tailored_content = ResumeContent.model_validate(state["tailored_resume"])
    original_resume = db.get(Resume, state["resume_id"])
    new_resume = Resume(
        user_id=original_resume.user_id,
        structured_content=tailored_content.model_dump(),
        version=original_resume.version + 1,
    )
    db.add(new_resume)
    db.flush()

    db.add(
        JDAnalysis(
            resume_id=new_resume.id,
            jd_text=state["jd_text"],
            score=state["tailored_score"]["score"],
            breakdown=state["tailored_score"],
        )
    )

    state["tailored_resume_id"] = new_resume.id
    run.context = dict(state)
    run.current_step = state["status"]
    run.status = "completed"
    db.commit()

    return _response(run, state)


@router.get("/{run_id}/result", response_model=TailoringStateResponse)
def get_tailoring_result(run_id: int, db: Session = Depends(get_db)) -> TailoringStateResponse:
    run = _get_run(run_id, db)
    state: TailoringState = run.context  # type: ignore[assignment]
    return _response(run, state)
