from datetime import datetime

from pydantic import BaseModel, ConfigDict


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


class ResumeResponse(BaseModel):
    id: int
    user_id: int
    structured_content: ResumeContent
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
