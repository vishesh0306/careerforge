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
    emphasis_focus: Optional[str]
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

{instructions}

Rules:
- Do NOT invent, add, or imply any skill or claim that is not explicitly supported by the confirmed additions \
below or the candidate's existing resume content.
- Never delete real, factual content (actual jobs, actual bullets, actual skills) — reordering and \
de-emphasizing what's less relevant to this application is fine; erasing true experience is not.
- Preserve everything about the resume that is already strong and not addressed by the instructions above.
"""

ADDITIONS_INSTRUCTIONS = """The candidate has confirmed they genuinely have the following additional skills/\
experience, with supporting detail where given. Incorporate ONLY these into the resume — add each to the most \
appropriate section (the skills list, and/or as a new or updated experience bullet if detail was given):

{confirmed_additions}"""

EMPHASIS_INSTRUCTIONS = """The candidate knows multiple technologies/stacks and wants THIS version of their \
resume to foreground their "{emphasis_focus}" experience specifically, since that is what this job is \
centered on:
- Reorder each skills list so "{emphasis_focus}"-related items appear first within their category.
- Reorder experience bullets within each job so "{emphasis_focus}"-related bullets come first.
- If the summary mentions multiple stacks, lead with "{emphasis_focus}".
- Do NOT delete bullets or skills about other stacks — just move them later/lower. The candidate still wants \
their full breadth visible, just not leading, since they apply to other kinds of roles too."""


def generate_gap_explanations(resume_text: str, jd_text: str, missing_terms: list[str]) -> dict[str, str]:
    if not missing_terms:
        return {}
    prompt = GAP_EXPLANATION_PROMPT.format(
        jd_text=jd_text, resume_text=resume_text, missing_terms=", ".join(missing_terms)
    )
    result = llm_client.generate_structured(prompt, _GapExplanationList, temperature=0.2)
    return {g.term: g.why_it_matters for g in result.gaps}


def tailor_resume(
    resume: ResumeContent,
    jd_text: str,
    confirmed_gaps: list[GapItem],
    emphasis_focus: Optional[str] = None,
) -> ResumeContent:
    instruction_blocks = []

    if confirmed_gaps:
        additions_lines = []
        for gap in confirmed_gaps:
            if gap.get("detail"):
                additions_lines.append(f"- {gap['term']}: {gap['detail']}")
            else:
                additions_lines.append(f"- {gap['term']} (candidate confirmed they have this; add to skills only)")
        instruction_blocks.append(ADDITIONS_INSTRUCTIONS.format(confirmed_additions="\n".join(additions_lines)))

    if emphasis_focus:
        instruction_blocks.append(EMPHASIS_INSTRUCTIONS.format(emphasis_focus=emphasis_focus))

    prompt = TAILOR_PROMPT.format(
        jd_text=jd_text,
        resume_json=resume.model_dump_json(),
        instructions="\n\n".join(instruction_blocks),
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
    emphasis_focus = state.get("emphasis_focus")

    # Emphasis-only requests (candidate already has the skill, just wants it foregrounded)
    # must still trigger regeneration even with zero confirmed gaps — only skip the LLM
    # call entirely when there is truly nothing to do.
    if confirmed_gaps or emphasis_focus:
        tailored = tailor_resume(resume, state["jd_text"], confirmed_gaps, emphasis_focus)
        # Tailoring reorders/rewords existing content and adds skills/bullets — it never changes
        # an experience entry's dates, so the years-of-experience figure from the original score
        # is still correct here and reusing it saves a redundant LLM call.
        candidate_years_experience = state["original_score"].get("candidate_years_experience")
        rescore = score_resume_against_jd(tailored, state["jd_text"], candidate_years_experience)
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
