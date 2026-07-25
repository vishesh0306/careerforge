from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.logging import log_transition
from app.core.ownership import get_owned_resume
from app.models import AutofillDraft, JobListing, User
from app.schemas.autofill import AutofillDraftRequest, AutofillDraftResponse
from app.schemas.resume import ResumeContent
from app.services.autofill.detection import detect_ats_platform
from app.services.autofill.runner import UnsupportedATSPlatformError, run_autofill_draft
from app.services.resume_renderer import render_resume_pdf

router = APIRouter()


@router.post("/{listing_id}/draft", response_model=AutofillDraftResponse, status_code=status.HTTP_201_CREATED)
async def create_autofill_draft(
    listing_id: int,
    body: AutofillDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutofillDraftResponse:
    listing = db.get(JobListing, listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"Job listing {listing_id} not found")

    resume = get_owned_resume(body.resume_id, current_user, db)

    platform = detect_ats_platform(listing.url)
    if platform is None:
        raise HTTPException(
            status_code=400, detail=f"No supported ATS platform detected for this listing's URL: {listing.url}"
        )

    content = ResumeContent.model_validate(resume.structured_content)
    resume_pdf_bytes = render_resume_pdf(content)
    resume_filename = f"resume_{resume.id}.pdf"

    try:
        result = await run_autofill_draft(listing.url, content.contact, resume_pdf_bytes, resume_filename)
    except UnsupportedATSPlatformError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        draft = AutofillDraft(
            job_listing_id=listing_id,
            resume_id=body.resume_id,
            ats_platform=platform,
            status="failed",
            filled_fields={},
            error=str(exc),
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)
        log_transition("autofill_draft", draft.id, draft.ats_platform, draft.status, error=draft.error)
        return AutofillDraftResponse(
            id=draft.id,
            job_listing_id=listing_id,
            resume_id=body.resume_id,
            ats_platform=platform,
            status="failed",
            filled_fields={},
            error=draft.error,
        )

    draft = AutofillDraft(
        job_listing_id=listing_id,
        resume_id=body.resume_id,
        ats_platform=result["ats_platform"],
        status="filled",
        filled_fields=result["filled_fields"],
        screenshot_base64=result["screenshot_base64"],
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    log_transition("autofill_draft", draft.id, draft.ats_platform, draft.status)

    return AutofillDraftResponse(
        id=draft.id,
        job_listing_id=listing_id,
        resume_id=body.resume_id,
        ats_platform=draft.ats_platform,
        status=draft.status,
        filled_fields=draft.filled_fields,
        screenshot_data_uri=f"data:image/png;base64,{draft.screenshot_base64}",
    )
