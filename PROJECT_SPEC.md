# CareerForge — Project Specification

## 1. What this is

CareerForge is a backend-first AI system that builds, scores, and tailors resumes against real job descriptions, finds matching job openings, preps the user for interviews based on the gaps it finds, and — as a later phase — drafts (but never blindly submits) job applications on company career pages.

It is built to be used by its own creator first: a backend engineer job-hunting for a 15+ LPA role in India. Every feature should work end-to-end for that use case before anything else is added.

## 2. Problem statement

Generic resume builders produce generic resumes. ATS-checker tools give a score with no real explanation. Job boards return noise, not ranked relevance. Tailoring a resume per job posting is manual, repetitive work most candidates skip — which is exactly why their resumes underperform ATS filters. CareerForge closes that loop: build once, score explainably, tailor per JD automatically, re-score to prove improvement, and surface the jobs worth applying to.

## 3. Target user

Primarily: the project owner, a backend software engineer (Python/Java, AWS, some AI/RAG exposure) actively job-hunting. Secondarily, designed so it could plausibly serve any tech job-seeker without a full rewrite.

## 4. Core features

### 4.1 Conversational Resume Builder
The user describes themselves in free text. The system does **not** passively transcribe this into a resume — it reasons like a hiring recruiter in the user's target field would, and:
- Identifies gaps or vague claims and asks targeted clarifying questions (e.g., "You said you 'worked on APIs' — which ones, what was your specific contribution, and what was the measurable outcome?").
- Adapts its questioning and judgment to the specific role/field the resume targets (a backend engineer resume and a graphic designer resume should trigger different follow-ups and different standards for what counts as a strong bullet point).
- Once it has enough material, drafts the full resume content and **shows it to the user for confirmation** before finalizing. The user can request changes; the system revises and re-confirms.
- Only after explicit user confirmation does it generate the final resume (structured data → rendered PDF).

### 4.2 JD-Aware Resume Alteration
Given an existing resume (uploaded, parsed) and a target JD:
- Parses the resume into the same structured schema used by the builder.
- Runs the ATS Scoring Engine (see 4.3) against the JD to get a baseline score and a specific gap list.
- Reasons like a senior person in that same role, hiring for that same role: what does this JD actually demand, and what would a strong candidate's resume emphasize that this one doesn't?
- Asks the user, per identified gap: "Do you actually have this skill/experience? Want it added?" — never fabricates experience the user didn't confirm.
- Regenerates the resume incorporating only user-confirmed additions, then re-runs the score to show the before/after improvement.

### 4.3 ATS Scoring Engine (shared by two entry points)
- **Against a specific JD**: user provides JD text (or URL/paste); score = embedding similarity (resume vs JD) + keyword/skill coverage (must-have and nice-to-have terms extracted from the JD via LLM, checked for presence/frequency in the resume). Output includes the numeric score **and** a plain-language explanation of what's missing or weak — never just a bare number.
- **Against a generic role**: user specifies a role + seniority (e.g., "Backend Engineer, 1 YOE"). The system synthesizes a representative "ideal JD" for that role via LLM, then reuses the same scoring logic against it.

### 4.4 Job Search Aggregator
User specifies preferences: role, years of experience, location, job type (full-time / intern / contract), work mode (WFH / hybrid / onsite), expected CTC. The system queries job-listing aggregator APIs (see Architecture doc for which ones — direct LinkedIn/Indeed/Naukri scraping is explicitly out of scope, see Section 6), filters by the stated preferences, and ranks results by ATS match score of the user's current resume against each listing's JD.

### 4.5 Interview Prep Generator
For any JD the user has scored/tailored against, generate a set of likely interview questions and suggested talking points derived specifically from the gap analysis between that JD and the resume — not generic "tell me about yourself" filler.

### 4.6 Auto-Fill Draft (Application Assistance)
For a selected job listing on a company's own career page (Greenhouse/Lever/Workday/Ashby/SmartRecruiters/iCIMS-style ATS-hosted forms), the system pre-fills the application form fields from the user's resume/profile data and **stops** — the user reviews and manually submits. The system never submits an application on the user's behalf. This is a later-phase feature (see Roadmap).

### 4.7 Full Pipeline / Automation Mode
A single orchestrated flow that chains: build/confirm resume → search jobs by preference → for each candidate job, tailor + score + rank → present shortlist with interview prep → (optionally) auto-fill drafts for selected listings. Human confirmation checkpoints from the individual features are preserved inside the automated flow — "automated" means orchestrated, not unsupervised.

## 5. Design principles (non-negotiable)

1. **Human confirms before anything is finalized or submitted.** Draft → review → confirm, at every stage that produces or changes a resume, or that would submit anything externally.
2. **Never fabricate experience.** The system may suggest what to add based on a JD, but only includes it if the user explicitly confirms they have it.
3. **Explainable, not just numeric.** Every ATS score comes with a reason. Every job ranking is traceable to the score that produced it.
4. **No ToS-violating automation.** No scraping or auto-submitting on LinkedIn/Indeed/Naukri or any platform that prohibits it. Job search uses legitimate aggregator APIs. Application filling targets the user's own submission action, not a bypass of platform protections.
5. **Runs on free-tier infrastructure.** Every external dependency chosen must have a workable free tier (see Architecture doc for the specific list). No feature should require a paid API key to demo end-to-end.

## 6. Explicitly out of scope (for this project)

- Scraping or automating LinkedIn, Indeed, Naukri, or any platform whose ToS prohibits it.
- Fully autonomous application submission anywhere, ever.
- A polished frontend (this phase of the project is backend-only; FastAPI's Swagger UI is the interface for now — see Architecture doc).
- Supporting non-tech career fields in v1 (design is field-agnostic in principle, but only backend/software roles need to work correctly for launch).

## 7. Success criteria

- A user can go from "nothing" to a finalized, confirmed, PDF resume via conversation alone.
- Given an existing resume and a real JD, the system produces a measurably higher ATS score after tailoring (a concrete "62 → 89"-style before/after).
- Job search returns real, relevant, ranked listings from legitimate APIs matching stated preferences.
- Every score, gap, and suggestion is explainable in plain language, not a black-box number.
- The full pipeline can run end-to-end without the user needing to know or touch the underlying API calls (even without a frontend — Swagger UI is sufficient for this).
