from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import CreatedAtMixin


class AutofillDraft(CreatedAtMixin, Base):
    __tablename__ = "autofill_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_listing_id: Mapped[int] = mapped_column(ForeignKey("job_listings.id"), nullable=False, index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    ats_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    filled_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    screenshot_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
