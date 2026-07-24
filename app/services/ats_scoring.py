import re
from datetime import date

from pydantic import BaseModel

from app.schemas.resume import ExperienceEntry, ResumeContent
from app.services.embeddings import cosine_similarity
from app.services.llm_client import llm_client

# Fixed, documented weighting — keep stable so before/after score comparisons stay meaningful.
KEYWORD_COMPONENT_WEIGHT = 0.5
SEMANTIC_COMPONENT_WEIGHT = 0.3
EXPERIENCE_COMPONENT_WEIGHT = 0.2
MUST_HAVE_WEIGHT = 0.7
NICE_TO_HAVE_WEIGHT = 0.3

# Structured-extraction calls are pinned to low temperature for run-to-run consistency.
EXTRACTION_TEMPERATURE = 0.0
FIT_COMMENT_TEMPERATURE = 0.2


class JDTerms(BaseModel):
    must_have: list[str]
    nice_to_have: list[str]
    min_years_required: float | None = None


class FitComment(BaseModel):
    comment: str


class CandidateExperience(BaseModel):
    total_years_experience: float


class ATSScoreResult(BaseModel):
    score: float
    must_have_present: list[str]
    must_have_missing: list[str]
    nice_to_have_present: list[str]
    nice_to_have_missing: list[str]
    semantic_similarity: float
    semantic_fit_comment: str
    min_years_required: float | None = None
    candidate_years_experience: float | None = None


JD_TERMS_PROMPT = """Extract the key skills, technologies, and qualifications from the job description below.

Classify each into:
- must_have: explicitly required or clearly essential qualifications (e.g. "required", "must have", core \
technologies repeatedly emphasized)
- nice_to_have: explicitly optional, preferred, or bonus qualifications (e.g. "nice to have", "preferred", \
"a plus")

Return each term as ONE atomic, specific technology/tool/qualification (e.g. "AWS Lambda", "5+ years Python", \
"Kubernetes") — not full sentences, and never a grouped or alternative list.

Critical: if the JD lists alternatives or groups (e.g. "Python, Go, or Java", "Git, Linux, Docker, CI/CD \
pipelines", "relational databases (PostgreSQL or MySQL)"), split it into SEPARATE individual items — one per \
technology — rather than one combined item. For example "Backend languages (Python, Go, Node.js, or Java)" \
must become four separate items: "Python", "Go", "Node.js", "Java".

Also extract min_years_required: the MINIMUM total years of professional experience explicitly required or \
implied by the seniority of this role (e.g. "3-6 years" → 3, "5+ years" → 5, "Senior" with no number stated → \
a reasonable minimum such as 5, "Junior"/"Entry-level"/no experience language at all → 0). Return it as a \
plain number, or null only if the role's seniority truly cannot be inferred at all.

Job description:
---
{jd_text}
---
"""

FIT_COMMENT_PROMPT = """You are a senior hiring manager reviewing how well a candidate's resume matches a job \
description.

Resume content:
---
{resume_text}
---

Job description:
---
{jd_text}
---

The candidate is missing these must-have requirements: {missing}

Write exactly ONE concise sentence giving your honest assessment of the candidate's fit for this role — \
mention their strongest relevant match and their most significant gap, if any. Do not restate the numeric \
score.
"""

CANDIDATE_EXPERIENCE_PROMPT = """Estimate the candidate's total years of professional work experience from the \
work history below.

Today's date: {today}

Rules:
- Sum the duration of each role. Treat "Present"/"Current" end dates as today's date above.
- If roles overlap in time (e.g. concurrent jobs), do not double-count the overlapping period.
- Internships and apprenticeships count as professional experience.
- If there is no work history at all, or no dates are given, return 0.
- Round to one decimal place.

Work history:
---
{experience_text}
---
"""

ROLE_JD_PROMPT = """Write a realistic, representative job description for the following role, as it would \
typically appear on a job board.

Role: {role}
Seniority level: {seniority}

Include a brief role/company summary, a "Responsibilities" section, and a "Requirements" section that \
clearly distinguishes required qualifications from preferred/nice-to-have ones. Use realistic, specific \
technologies and expectations for this role and seniority — not generic filler.
"""


def resume_content_to_text(resume: ResumeContent) -> str:
    lines: list[str] = []
    if resume.contact.name:
        lines.append(resume.contact.name)
    if resume.summary:
        lines.append(resume.summary)

    all_skills = [
        *resume.skills.languages,
        *resume.skills.frameworks,
        *resume.skills.tools,
        *resume.skills.cloud_devops,
        *resume.skills.other,
    ]
    if all_skills:
        lines.append("Skills: " + ", ".join(all_skills))

    for job in resume.experience:
        lines.append(f"{job.title} at {job.company} ({job.start_date} - {job.end_date})".strip())
        lines.extend(job.bullets)

    for project in resume.projects:
        lines.append(f"Project: {project.name}")
        lines.extend(project.bullets)
        if project.tech_stack:
            lines.append("Tech: " + ", ".join(project.tech_stack))

    for edu in resume.education:
        lines.append(f"{edu.degree}, {edu.institution} ({edu.dates})".strip())

    if resume.certifications:
        lines.append("Certifications: " + ", ".join(resume.certifications))

    if resume.achievements:
        lines.append("Achievements: " + ", ".join(resume.achievements))

    return "\n".join(lines)


def extract_jd_terms(jd_text: str) -> JDTerms:
    prompt = JD_TERMS_PROMPT.format(jd_text=jd_text)
    return llm_client.generate_structured(prompt, JDTerms, temperature=EXTRACTION_TEMPERATURE)


def _contains_as_word(needle: str, text_lower: str) -> bool:
    """Word-boundary substring check — avoids false positives like "Go" matching inside
    "Django", which plain substring containment would report as present."""
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", text_lower) is not None


def _term_present(term: str, text_lower: str) -> bool:
    term_lower = term.lower().strip()
    if _contains_as_word(term_lower, text_lower):
        return True

    # Defense-in-depth: if the LLM still returned a compound/alternative term despite
    # being instructed not to (e.g. "Git, Linux, Docker, CI/CD pipelines"), treat it as
    # present if any individual sub-part matches, rather than requiring the whole phrase.
    parts = re.split(r",| or | / |/| & | and |\(|\)", term_lower)
    sub_terms = [p.strip() for p in parts if len(p.strip()) > 2]
    if len(sub_terms) > 1:
        return any(_contains_as_word(sub, text_lower) for sub in sub_terms)
    return False


def compute_keyword_coverage(
    resume_text: str, terms: JDTerms
) -> tuple[float, list[str], list[str], list[str], list[str]]:
    text_lower = resume_text.lower()

    must_present = [t for t in terms.must_have if _term_present(t, text_lower)]
    must_missing = [t for t in terms.must_have if t not in must_present]
    nice_present = [t for t in terms.nice_to_have if _term_present(t, text_lower)]
    nice_missing = [t for t in terms.nice_to_have if t not in nice_present]

    must_coverage = len(must_present) / len(terms.must_have) if terms.must_have else 1.0
    nice_coverage = len(nice_present) / len(terms.nice_to_have) if terms.nice_to_have else 1.0

    keyword_score = MUST_HAVE_WEIGHT * must_coverage + NICE_TO_HAVE_WEIGHT * nice_coverage
    return keyword_score, must_present, must_missing, nice_present, nice_missing


def generate_fit_comment(resume_text: str, jd_text: str, must_missing: list[str]) -> str:
    missing_str = ", ".join(must_missing) if must_missing else "none"
    prompt = FIT_COMMENT_PROMPT.format(resume_text=resume_text, jd_text=jd_text, missing=missing_str)
    result = llm_client.generate_structured(prompt, FitComment, temperature=FIT_COMMENT_TEMPERATURE)
    return result.comment.strip()


def _format_experience_for_dating(experience: list[ExperienceEntry]) -> str:
    lines = []
    for job in experience:
        lines.append(f"{job.title} at {job.company}: {job.start_date} to {job.end_date or 'Present'}")
    return "\n".join(lines)


def extract_candidate_years_experience(experience: list[ExperienceEntry]) -> float:
    if not experience:
        return 0.0
    prompt = CANDIDATE_EXPERIENCE_PROMPT.format(
        today=date.today().isoformat(), experience_text=_format_experience_for_dating(experience)
    )
    result = llm_client.generate_structured(prompt, CandidateExperience, temperature=EXTRACTION_TEMPERATURE)
    return result.total_years_experience


def compute_experience_fit(candidate_years: float | None, min_years_required: float | None) -> float:
    """1.0 if the JD states no minimum, or the candidate meets/exceeds it; otherwise the
    proportion of the requirement the candidate's experience covers (never negative)."""
    if not min_years_required or min_years_required <= 0:
        return 1.0
    if candidate_years is None:
        return 1.0
    if candidate_years >= min_years_required:
        return 1.0
    return max(0.0, candidate_years / min_years_required)


def score_resume_against_jd(resume: ResumeContent, jd_text: str) -> ATSScoreResult:
    resume_text = resume_content_to_text(resume)
    terms = extract_jd_terms(jd_text)
    keyword_score, must_present, must_missing, nice_present, nice_missing = compute_keyword_coverage(
        resume_text, terms
    )
    semantic_similarity = cosine_similarity(resume_text, jd_text)
    candidate_years = extract_candidate_years_experience(resume.experience)
    experience_fit = compute_experience_fit(candidate_years, terms.min_years_required)

    combined = (
        KEYWORD_COMPONENT_WEIGHT * keyword_score
        + SEMANTIC_COMPONENT_WEIGHT * semantic_similarity
        + EXPERIENCE_COMPONENT_WEIGHT * experience_fit
    )
    score = round(combined * 100, 1)

    comment = generate_fit_comment(resume_text, jd_text, must_missing)

    return ATSScoreResult(
        score=score,
        must_have_present=must_present,
        must_have_missing=must_missing,
        nice_to_have_present=nice_present,
        nice_to_have_missing=nice_missing,
        semantic_similarity=round(semantic_similarity, 3),
        semantic_fit_comment=comment,
        min_years_required=terms.min_years_required,
        candidate_years_experience=candidate_years,
    )


def synthesize_ideal_jd(role: str, seniority: str) -> str:
    prompt = ROLE_JD_PROMPT.format(role=role, seniority=seniority)
    return llm_client.generate_text(prompt)
