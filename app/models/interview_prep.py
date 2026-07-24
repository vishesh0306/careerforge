from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import CreatedAtMixin


class InterviewPrep(CreatedAtMixin, Base):
    __tablename__ = "interview_preps"

    id: Mapped[int] = mapped_column(primary_key=True)
    jd_analysis_id: Mapped[int] = mapped_column(ForeignKey("jd_analyses.id"), nullable=False, index=True)
    questions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
