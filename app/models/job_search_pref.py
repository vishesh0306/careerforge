from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import CreatedAtMixin


class JobSearchPref(CreatedAtMixin, Base):
    __tablename__ = "job_search_prefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    work_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expected_ctc: Mapped[str | None] = mapped_column(String(100), nullable=True)
