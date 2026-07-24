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
    other: list[str] = Field(
        default=[],
        description="Skills that don't fit languages/frameworks/tools/cloud_devops — e.g. databases, "
        "operating systems, core CS concepts, design patterns. Never drop a stated skill for lack of "
        "a matching bucket; put it here instead.",
    )


class ExperienceEntry(BaseModel):
    company: str = ""
    title: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[str] = []


class ProjectEntry(BaseModel):
    name: str = ""
    bullets: list[str] = Field(
        default=[],
        description="Each distinct point about the project as its own bullet — do not compress multiple "
        "points into a single sentence.",
    )
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
    achievements: list[str] = Field(
        default=[],
        description="Awards, hackathon wins, competition rankings, notable recognitions — distinct from "
        "certifications (credentials/courses). Extract this as its own section, don't drop it or merge "
        "it into certifications.",
    )


class ResumeContentPatch(BaseModel):
    """Partial update for a resume's structured content — deterministic, no LLM involved.

    A section left out entirely (not sent at all) is untouched. `summary` and any scalar field you
    send inside `contact` overwrite the existing value. Everything else is additive: list sections
    (`skills.*`, `experience`, `projects`, `education`, `certifications`, `achievements`,
    `contact.links`) get the items you send APPENDED to what's already there — you never need to
    resend existing items just to add one. There's no way to remove or reorder existing items, or to
    edit an existing experience/project/education entry in place, through this endpoint — a sent entry
    is always a new entry.
    """

    contact: Optional[ContactInfo] = Field(
        None,
        description="Any scalar field you include (name/email/phone/location) overwrites the existing value; "
        "fields you omit are left as-is. `links` is additive — items you send are appended, not replacing.",
    )
    summary: Optional[str] = Field(None, description="Overwrites the summary if provided.")
    skills: Optional[Skills] = Field(
        None,
        description="Each sub-list you include (languages/frameworks/tools/cloud_devops/other) is additive — "
        "items you send are appended to the existing list, not replacing it.",
    )
    experience: Optional[list[ExperienceEntry]] = Field(
        None, description="Entries you send are appended as new experience entries, not replacing the list."
    )
    projects: Optional[list[ProjectEntry]] = Field(
        None, description="Entries you send are appended as new projects, not replacing the list."
    )
    education: Optional[list[EducationEntry]] = Field(
        None, description="Entries you send are appended as new education entries, not replacing the list."
    )
    certifications: Optional[list[str]] = Field(
        None, description="Certifications you send are appended to the existing list (exact duplicates skipped)."
    )
    achievements: Optional[list[str]] = Field(
        None, description="Achievements you send are appended to the existing list (exact duplicates skipped)."
    )


def _append_dedupe(existing: list, new: list) -> list:
    merged = list(existing)
    for item in new:
        if item not in merged:
            merged.append(item)
    return merged


def merge_resume_patch(existing: dict, patch: "ResumeContentPatch") -> dict:
    """Applies a ResumeContentPatch to an existing structured_content dict — see ResumeContentPatch
    for the merge semantics (scalars overwrite, lists are additive)."""
    updates = patch.model_dump(exclude_unset=True)
    merged = dict(existing)

    if "contact" in updates:
        existing_contact = dict(existing.get("contact") or {})
        new_contact = updates["contact"]
        merged_contact = {**existing_contact, **new_contact}
        if "links" in new_contact:
            merged_contact["links"] = _append_dedupe(existing_contact.get("links", []), new_contact["links"])
        merged["contact"] = merged_contact

    if "summary" in updates:
        merged["summary"] = updates["summary"]

    if "skills" in updates:
        existing_skills = dict(existing.get("skills") or {})
        new_skills = updates["skills"]
        merged_skills = dict(existing_skills)
        for key in ("languages", "frameworks", "tools", "cloud_devops", "other"):
            if key in new_skills:
                merged_skills[key] = _append_dedupe(existing_skills.get(key, []), new_skills[key])
        merged["skills"] = merged_skills

    for list_field in ("experience", "projects", "education"):
        if list_field in updates:
            merged[list_field] = list(existing.get(list_field, [])) + updates[list_field]

    if "certifications" in updates:
        merged["certifications"] = _append_dedupe(existing.get("certifications", []), updates["certifications"])

    if "achievements" in updates:
        merged["achievements"] = _append_dedupe(existing.get("achievements", []), updates["achievements"])

    return merged


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
