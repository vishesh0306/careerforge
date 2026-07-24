from typing import Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.schemas.resume import ResumeContent
from app.services.ats_scoring import ATSScoreResult, resume_content_to_text, score_resume_against_jd
from app.services.llm_client import llm_client


class GapItem(TypedDict):
    term: str
    category: Literal["must_have", "nice_to_have"]
    why_it_matters: str
    confirmed: Optional[bool]
    detail: Optional[str]


class TailoringState(TypedDict):
    resume_id: int
    jd_text: str
    original_resume: dict
    original_score: dict
    gaps: list[GapItem]
    tailored_resume: Optional[dict]
    tailored_score: Optional[dict]
    status: Literal["AWAITING_GAP_CONFIRM", "RESCORED"]
    entry_point: Literal["score_and_review", "tailor_and_rescore"]


class _GapExplanation(BaseModel):
    term: str
    why_it_matters: str


class _GapExplanationList(BaseModel):
    gaps: list[_GapExplanation]


GAP_EXPLANATION_PROMPT = """You are a senior hiring manager for the role described in the job description \
below, reviewing a candidate's resume.

Job description:
---
{jd_text}
---

Candidate's current resume:
---
{resume_text}
---

The following requirements appear to be missing or not evidenced in the resume: {missing_terms}

For each one, explain in one or two sentences WHY it specifically matters for THIS job — grounded in what \
the job description actually emphasizes and how the role/team would use it — not generic career advice or a \
canned definition of the technology. Return one explanation per listed term.
"""

TAILOR_PROMPT = """You are a senior hiring manager and resume writer tailoring a candidate's resume for a \
specific job description.

Job description:
---
{jd_text}
---

Current resume (JSON):
{resume_json}

The candidate has confirmed they genuinely have the following additional skills/experience, with supporting \
detail where given:

{confirmed_additions}

Incorporate ONLY these confirmed additions into the resume — add each to the most appropriate section (the \
skills list, and/or as a new or updated experience bullet if specific supporting detail was given).

Rules:
- Do NOT invent, add, or imply any skill or claim that is not explicitly listed above.
- Preserve everything else about the resume that was already strong — do not remove, reword away, or weaken \
existing content that isn't related to these additions.
"""


def generate_gap_explanations(resume_text: str, jd_text: str, missing_terms: list[str]) -> dict[str, str]:
    if not missing_terms:
        return {}
    prompt = GAP_EXPLANATION_PROMPT.format(
        jd_text=jd_text, resume_text=resume_text, missing_terms=", ".join(missing_terms)
    )
    result = llm_client.generate_structured(prompt, _GapExplanationList, temperature=0.2)
    return {g.term: g.why_it_matters for g in result.gaps}


def tailor_resume(resume: ResumeContent, jd_text: str, confirmed_gaps: list[GapItem]) -> ResumeContent:
    additions_lines = []
    for gap in confirmed_gaps:
        if gap.get("detail"):
            additions_lines.append(f"- {gap['term']}: {gap['detail']}")
        else:
            additions_lines.append(f"- {gap['term']} (candidate confirmed they have this; add to skills only)")

    prompt = TAILOR_PROMPT.format(
        jd_text=jd_text,
        resume_json=resume.model_dump_json(),
        confirmed_additions="\n".join(additions_lines),
    )
    return llm_client.generate_structured(prompt, ResumeContent, temperature=0.2)


def score_and_review_node(state: TailoringState) -> TailoringState:
    resume = ResumeContent.model_validate(state["original_resume"])
    score_result = score_resume_against_jd(resume, state["jd_text"])
    state["original_score"] = score_result.model_dump()

    missing = [(t, "must_have") for t in score_result.must_have_missing] + [
        (t, "nice_to_have") for t in score_result.nice_to_have_missing
    ]
    explanation_map = generate_gap_explanations(
        resume_content_to_text(resume), state["jd_text"], [t for t, _ in missing]
    )

    state["gaps"] = [
        {
            "term": term,
            "category": category,
            "why_it_matters": explanation_map.get(term, ""),
            "confirmed": None,
            "detail": None,
        }
        for term, category in missing
    ]
    state["status"] = "AWAITING_GAP_CONFIRM"
    return state


def tailor_and_rescore_node(state: TailoringState) -> TailoringState:
    resume = ResumeContent.model_validate(state["original_resume"])
    confirmed_gaps = [g for g in state["gaps"] if g["confirmed"]]

    if confirmed_gaps:
        tailored = tailor_resume(resume, state["jd_text"], confirmed_gaps)
        rescore = score_resume_against_jd(tailored, state["jd_text"])
    else:
        tailored = resume
        rescore = ATSScoreResult.model_validate(state["original_score"])

    state["tailored_resume"] = tailored.model_dump()
    state["tailored_score"] = rescore.model_dump()
    state["status"] = "RESCORED"
    return state


def _route_entry(state: TailoringState) -> str:
    return state["entry_point"]


def build_graph():
    graph = StateGraph(TailoringState)
    graph.add_node("score_and_review", score_and_review_node)
    graph.add_node("tailor_and_rescore", tailor_and_rescore_node)

    graph.add_conditional_edges(
        START, _route_entry, {"score_and_review": "score_and_review", "tailor_and_rescore": "tailor_and_rescore"}
    )
    graph.add_edge("score_and_review", END)
    graph.add_edge("tailor_and_rescore", END)

    return graph.compile()


jd_tailoring_graph = build_graph()
