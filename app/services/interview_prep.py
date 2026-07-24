from pydantic import BaseModel

from app.schemas.resume import ResumeContent
from app.services.ats_scoring import resume_content_to_text
from app.services.llm_client import llm_client

GENERATION_TEMPERATURE = 0.3


class InterviewQuestion(BaseModel):
    question: str
    why_asked: str
    talking_points: list[str]


class InterviewPrepContent(BaseModel):
    questions: list[InterviewQuestion]


INTERVIEW_PREP_PROMPT = """You are a senior hiring manager preparing a candidate for their upcoming interview \
for this specific role, using a gap analysis already run between their resume and the job description.

Job description:
---
{jd_text}
---

Candidate's resume:
---
{resume_text}
---

Gap analysis already computed for this candidate against this JD:
- Must-have requirements the resume DOES cover: {must_have_present}
- Must-have requirements the resume is MISSING: {must_have_missing}
- Nice-to-have requirements covered: {nice_to_have_present}
- Nice-to-have requirements missing: {nice_to_have_missing}
- Years of experience: JD requires {min_years_required}, candidate has approximately {candidate_years_experience}
- Overall fit assessment: {semantic_fit_comment}

Generate 6-10 realistic interview questions this candidate is specifically likely to be asked for THIS role, \
grounded in THIS job description and THIS gap analysis — never generic, boilerplate interview questions that \
could apply to any job. Include a mix of:
- Questions probing the specific missing must-have requirements listed above
- Questions letting the candidate showcase the must-haves/nice-to-haves they DO have, grounded in what's \
actually in their resume
- If there is a years-of-experience gap, at least one question addressing that directly

For each question, also provide:
- why_asked: one concise sentence tying the question to a specific requirement or gap from the analysis above \
— not a generic reason.
- talking_points: 2-4 specific points the candidate should raise when answering. Where the resume has relevant \
content, reference it specifically (actual companies, projects, or bullets from the resume above) rather than \
generic advice. For a gap the candidate doesn't have direct experience in, suggest how they could honestly \
bridge it (transferable experience, related exposure, concrete willingness to learn) — never fabricate \
experience they don't have.
"""


def generate_interview_prep(resume: ResumeContent, jd_text: str, gap_breakdown: dict) -> InterviewPrepContent:
    resume_text = resume_content_to_text(resume)
    prompt = INTERVIEW_PREP_PROMPT.format(
        jd_text=jd_text,
        resume_text=resume_text,
        must_have_present=", ".join(gap_breakdown.get("must_have_present") or []) or "none",
        must_have_missing=", ".join(gap_breakdown.get("must_have_missing") or []) or "none",
        nice_to_have_present=", ".join(gap_breakdown.get("nice_to_have_present") or []) or "none",
        nice_to_have_missing=", ".join(gap_breakdown.get("nice_to_have_missing") or []) or "none",
        min_years_required=gap_breakdown.get("min_years_required"),
        candidate_years_experience=gap_breakdown.get("candidate_years_experience"),
        semantic_fit_comment=gap_breakdown.get("semantic_fit_comment") or "not available",
    )
    return llm_client.generate_structured(prompt, InterviewPrepContent, temperature=GENERATION_TEMPERATURE)
