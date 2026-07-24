from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ContactInfo(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = []


class Skills(BaseModel):
    languages: list[str] = []
    frameworks: list[str] = []
    tools: list[str] = []
    cloud_devops: list[str] = []


class ExperienceEntry(BaseModel):
    company: str = ""
    title: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[str] = []


class ProjectEntry(BaseModel):
    name: str = ""
    description: str = ""
    tech_stack: list[str] = []
    link: str = ""


class EducationEntry(BaseModel):
    institution: str = ""
    degree: str = ""
    dates: str = ""


class ResumeContent(BaseModel):
    """The core structured resume representation — see ARCHITECTURE.md Section 3.
    Every feature (parser, builder, tailoring, rendering) reads/writes this shape."""

    contact: ContactInfo = ContactInfo()
    summary: str = ""
    skills: Skills = Skills()
    experience: list[ExperienceEntry] = []
    projects: list[ProjectEntry] = []
    education: list[EducationEntry] = []
    certifications: list[str] = []


class ResumeContentPatch(BaseModel):
    """Partial update for a resume's structured content — deterministic, no LLM involved.

    Only top-level sections included in the request are replaced wholesale; any section left out
    (not sent at all) is untouched. There is no way to partially edit within a section — send the
    whole section (e.g. the whole `experience` list) with your changes applied.
    """

    contact: Optional[ContactInfo] = Field(None, description="Replaces the whole contact block if provided.")
    summary: Optional[str] = Field(None, description="Replaces the summary if provided.")
    skills: Optional[Skills] = Field(None, description="Replaces the whole skills block if provided.")
    experience: Optional[list[ExperienceEntry]] = Field(
        None, description="Replaces the whole experience list if provided."
    )
    projects: Optional[list[ProjectEntry]] = Field(None, description="Replaces the whole projects list if provided.")
    education: Optional[list[EducationEntry]] = Field(
        None, description="Replaces the whole education list if provided."
    )
    certifications: Optional[list[str]] = Field(
        None, description="Replaces the whole certifications list if provided."
    )


class ResumeResponse(BaseModel):
    id: int
    user_id: int
    structured_content: ResumeContent
    version: int
    source: str
    label: Optional[str] = None
    parent_resume_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
