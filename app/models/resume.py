from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import TimestampMixin


class Resume(TimestampMixin, Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    structured_content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # "uploaded" | "builder" | "tailored" — how this resume row came to exist.
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # Auto-generated human-readable label so a user's resumes are distinguishable
    # when listed, e.g. "Uploaded resume", "Built for Backend Engineer",
    # "Tailored — Django focus".
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # For tailored resumes: the resume this one was tailored from. Null for
    # uploaded/builder-created resumes, which have no lineage.
    parent_resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id"), nullable=True)
