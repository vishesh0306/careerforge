import json
from typing import Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.schemas.resume import ResumeContent
from app.services.llm_client import llm_client


class Message(TypedDict):
    role: Literal["recruiter", "candidate"]
    content: str


class BuilderState(TypedDict):
    target_field: str
    messages: list[Message]
    status: Literal["INTAKE", "CLARIFYING", "DRAFT_READY", "AWAITING_CONFIRM", "FINALIZED"]
    clarifying_question: Optional[str]
    draft: Optional[dict]
    revision_feedback: Optional[str]
    entry_point: Literal["assess", "revise"]
    base_resume: Optional[dict]
    base_resume_id: Optional[int]
    emphasis_focus: Optional[str]


class AssessmentResult(BaseModel):
    ready_to_draft: bool
    clarifying_question: str = ""


ASSESS_PROMPT = """You are a senior hiring manager and experienced technical recruiter specializing in the \
field of "{target_field}". You are interviewing a candidate to help them build a strong, accurate resume.

Apply the standards a real hiring manager in this specific field would apply. Different fields value \
different kinds of evidence (e.g. a backend engineer should quantify latency/scale/cost impact; a graphic \
designer should describe creative process, tools used, and client/stakeholder outcomes) — adapt your \
judgment and questions to what actually matters in "{target_field}".
{base_resume_note}{emphasis_assess_note}
Conversation so far:
{transcript}

Decide:
1. Is there enough SPECIFIC, CONCRETE information (roles, companies, projects, measurable outcomes, tools \
or skills actually used) to draft a genuinely strong resume for this field? Vague claims like "worked on \
APIs" or "helped the team" are NOT enough — you need specifics.
2. If not enough, ask exactly ONE targeted, specific clarifying question addressing the biggest gap or \
vaguest claim so far. Reference what the candidate actually said — do not ask a generic filler question.
3. If there is enough, set ready_to_draft to true and leave clarifying_question empty.
"""

BASE_RESUME_NOTE = """
The candidate already has an existing resume on file — do NOT ask them to re-state information already \
present in it. Only ask about what's new, what has changed, or what they explicitly want to add or update in \
this conversation.

Existing resume (JSON):
{base_resume_json}
"""

EMPHASIS_ASSESS_NOTE = """
The candidate wants this resume to specifically foreground their "{emphasis_focus}" experience. When deciding \
what to ask about, prioritize digging deeper into their "{emphasis_focus}"-related work — get specific, \
quantified detail there — over other areas, unless something else is critically vague or missing.
"""

EMPHASIS_DRAFT_INSTRUCTIONS = """
The candidate knows multiple technologies/stacks and wants THIS resume to foreground their "{emphasis_focus}" \
experience specifically:
- Reorder each skills list so "{emphasis_focus}"-related items appear first within their category.
- Reorder experience bullets within each job so "{emphasis_focus}"-related bullets come first.
- If the summary mentions multiple stacks, lead with "{emphasis_focus}".
- Do NOT omit or delete bullets or skills about other stacks the candidate mentioned — just move them later/ \
lower. The candidate still wants their full breadth visible, just not leading.
"""

DRAFT_PROMPT = """You are a senior hiring manager and technical recruiter specializing in "{target_field}", \
now drafting a resume for the candidate based ONLY on what they have told you in this conversation.

Rules:
- Use ONLY information explicitly provided by the candidate below. Do NOT invent companies, dates, \
metrics, or skills the candidate did not state.
- Where the candidate gave concrete numbers or outcomes, use them. Do not add fabricated quantification.
- Write experience bullet points as strong, action-verb-led achievement statements using the candidate's \
own facts — tighten the language, but do not add facts that were not given.
- Leave any schema field blank or empty if the candidate never provided that information.
{emphasis_draft_instructions}
Conversation:
{transcript}
"""

DRAFT_PROMPT_FROM_BASE = """You are a senior hiring manager and technical recruiter specializing in \
"{target_field}", updating a candidate's EXISTING resume based on a follow-up conversation.

Existing resume (JSON) — this is the candidate's current resume:
{base_resume_json}

Conversation since then:
{transcript}

Rules:
- Preserve everything in the existing resume that the conversation didn't address or contradict — do not \
regenerate from scratch, and do not remove or reword content that is still accurate.
- Incorporate new information from the conversation: new roles, updated bullets, added skills, corrections, \
etc. — wherever the candidate gave new or updated detail.
- If the conversation implies correcting or removing something from the existing resume (e.g. "that role \
actually ended in 2023, not 2024"), apply that correction.
- Use ONLY information explicitly provided — either already in the existing resume, or stated in this \
conversation. Do NOT invent companies, dates, metrics, or skills that were never stated.
{emphasis_draft_instructions}"""

REVISE_PROMPT = """You are a senior hiring manager and technical recruiter specializing in "{target_field}". \
Below is a draft resume you previously produced for a candidate, and their feedback on it.

Revise the resume to incorporate the candidate's feedback. Preserve everything about the draft that the \
feedback did not ask to change — do not regenerate from scratch, and do not remove or weaken content the \
candidate did not ask you to change. Do not invent any new facts beyond what the feedback states.

Current draft (JSON):
{draft_json}

Candidate feedback:
{feedback}
"""


def _format_transcript(state: BuilderState) -> str:
    lines = [f"Target field: {state['target_field']}", ""]
    for message in state["messages"]:
        speaker = "Recruiter" if message["role"] == "recruiter" else "Candidate"
        lines.append(f"{speaker}: {message['content']}")
    return "\n".join(lines)


def assess_node(state: BuilderState) -> BuilderState:
    base_resume_note = ""
    if state.get("base_resume"):
        base_resume_note = BASE_RESUME_NOTE.format(base_resume_json=json.dumps(state["base_resume"]))

    emphasis_assess_note = ""
    if state.get("emphasis_focus"):
        emphasis_assess_note = EMPHASIS_ASSESS_NOTE.format(emphasis_focus=state["emphasis_focus"])

    prompt = ASSESS_PROMPT.format(
        target_field=state["target_field"],
        base_resume_note=base_resume_note,
        emphasis_assess_note=emphasis_assess_note,
        transcript=_format_transcript(state),
    )
    result = llm_client.generate_structured(prompt, AssessmentResult)

    if result.ready_to_draft:
        state["status"] = "DRAFT_READY"
        state["clarifying_question"] = None
    else:
        state["status"] = "CLARIFYING"
        state["clarifying_question"] = result.clarifying_question
        state["messages"].append({"role": "recruiter", "content": result.clarifying_question})
    return state


def draft_node(state: BuilderState) -> BuilderState:
    emphasis_draft_instructions = ""
    if state.get("emphasis_focus"):
        emphasis_draft_instructions = EMPHASIS_DRAFT_INSTRUCTIONS.format(emphasis_focus=state["emphasis_focus"])

    if state.get("base_resume"):
        prompt = DRAFT_PROMPT_FROM_BASE.format(
            target_field=state["target_field"],
            base_resume_json=json.dumps(state["base_resume"]),
            emphasis_draft_instructions=emphasis_draft_instructions,
            transcript=_format_transcript(state),
        )
    else:
        prompt = DRAFT_PROMPT.format(
            target_field=state["target_field"],
            emphasis_draft_instructions=emphasis_draft_instructions,
            transcript=_format_transcript(state),
        )
    draft = llm_client.generate_structured(prompt, ResumeContent)

    state["draft"] = draft.model_dump()
    state["status"] = "AWAITING_CONFIRM"
    return state


def revise_node(state: BuilderState) -> BuilderState:
    prompt = REVISE_PROMPT.format(
        target_field=state["target_field"],
        draft_json=ResumeContent.model_validate(state["draft"]).model_dump_json(),
        feedback=state["revision_feedback"],
    )
    revised = llm_client.generate_structured(prompt, ResumeContent)

    state["draft"] = revised.model_dump()
    state["status"] = "AWAITING_CONFIRM"
    state["revision_feedback"] = None
    return state


def _route_after_assess(state: BuilderState) -> str:
    return "draft" if state["status"] == "DRAFT_READY" else END


def _route_entry(state: BuilderState) -> str:
    return state["entry_point"]


def build_graph():
    graph = StateGraph(BuilderState)
    graph.add_node("assess", assess_node)
    graph.add_node("draft", draft_node)
    graph.add_node("revise", revise_node)

    graph.add_conditional_edges(START, _route_entry, {"assess": "assess", "revise": "revise"})
    graph.add_conditional_edges("assess", _route_after_assess, {"draft": "draft", END: END})
    graph.add_edge("draft", END)
    graph.add_edge("revise", END)

    return graph.compile()


resume_builder_graph = build_graph()
