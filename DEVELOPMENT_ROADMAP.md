# CareerForge — Development Roadmap

Read this alongside `PROJECT_SPEC.md` and `ARCHITECTURE.md`. Work through phases **in order**. Do not start a phase until the previous phase's testing checklist is fully green. Check off each box as you complete it.

Each phase ends with a **Testing & Verification** section. This is not optional busywork — it exists so that at the end of every phase, the application is in a known-working state before more complexity is layered on. If a test fails, fix it before moving on; do not carry broken behavior into the next phase.

---

## Phase 0 — Project Scaffolding & Environment

**Goal:** A running, empty FastAPI app with DB and Redis connectivity confirmed, before any feature code is written.

- [ ] Initialize repo with the folder structure from `ARCHITECTURE.md` Section 7
- [ ] Set up virtual environment + `requirements.txt` (FastAPI, uvicorn, SQLAlchemy, Alembic, pydantic, python-dotenv, pytest, httpx)
- [ ] Create `.env.example` listing every required env var (see Architecture Section 6); create local `.env` (gitignored)
- [ ] Set up PostgreSQL (Supabase/Neon free tier) and Redis (Upstash free tier); confirm connection strings work
- [ ] Implement `app/main.py` with a `/health` endpoint
- [ ] Set up Alembic and confirm `alembic upgrade head` runs cleanly against an empty schema
- [ ] Add `.gitignore` (must exclude `.env`, `__pycache__`, `.venv`)
- [ ] Initial git commit — **do not include any AI co-author trailers in the commit message** (see note at bottom of this file)

**Testing & Verification**
- [ ] `uvicorn app.main:app --reload` starts with no errors
- [ ] `GET /health` returns 200 with a JSON status payload
- [ ] `alembic upgrade head` and `alembic downgrade base` both succeed against the real DB
- [ ] `pytest` runs (even with zero tests collected) without configuration errors

---

## Phase 1 — Data Models & DB Schema

**Goal:** All core tables exist and are migration-tracked, matching the resume JSON schema from `ARCHITECTURE.md` Section 3.

- [ ] `users` table (id, email, hashed_password, created_at)
- [ ] `resumes` table (id, user_id, structured_content JSONB, version, created_at, updated_at)
- [ ] `pipeline_runs` table (id, user_id, run_type, current_step, status, context JSONB, created_at, updated_at)
- [ ] `jd_analyses` table (id, resume_id, jd_text, score, breakdown JSONB, created_at)
- [ ] `job_search_prefs` table (id, user_id, role, experience_years, location, job_type, work_mode, expected_ctc)
- [ ] `job_listings` table (id, source, external_id, title, company, jd_text, url, location, fetched_at)
- [ ] Alembic migration generated and applied for all of the above

**Testing & Verification**
- [ ] Fresh DB + `alembic upgrade head` creates every table with correct columns/types
- [ ] Manually insert and query one row per table via a scratch script or `psql` — confirm JSONB columns round-trip correctly
- [ ] Run `pytest tests/models/` (write minimal model-creation tests) — all pass

---

## Phase 2 — LLM Integration Layer

**Goal:** A single, reliable client wrapper around Gemini that the rest of the app calls — never call the LLM SDK directly from feature code.

- [ ] `app/services/llm_client.py` — wraps Gemini calls, supports plain text and constrained JSON-schema output
- [ ] Retry-with-backoff on transient failures (rate limit, timeout)
- [ ] Timeout bound on every call
- [ ] A reusable "generate structured JSON matching schema X" helper (used by parsing, gap-extraction, resume generation, etc.)
- [ ] Config for `GEMINI_API_KEY` loaded from env, fails fast with a clear error if missing

**Testing & Verification**
- [ ] Unit test with a mocked Gemini response confirms retry logic triggers on simulated failure
- [ ] Live smoke test: call the client with a trivial prompt, confirm a real response comes back
- [ ] Live smoke test: call the structured-JSON helper with a simple schema (e.g., `{"greeting": "string"}`), confirm valid JSON matching the schema is returned
- [ ] Missing API key produces a clear startup/runtime error, not a silent failure

---

## Phase 3 — Resume Schema & Resume Parser

**Goal:** Given an uploaded PDF/DOCX resume, produce the structured JSON from `ARCHITECTURE.md` Section 3.

- [ ] `POST /resumes/upload` endpoint accepting PDF/DOCX
- [ ] Text extraction via `pdfplumber` (PDF) and `python-docx` (DOCX)
- [ ] LLM call (via Phase 2's structured-JSON helper) mapping raw text into the resume schema
- [ ] Store result in `resumes` table
- [ ] Handle malformed/unparseable uploads gracefully (clear error, not a 500 crash)

**Testing & Verification**
- [ ] Upload a real PDF resume — confirm structured JSON is stored and every section (contact, experience, skills, etc.) is populated correctly
- [ ] Upload a real DOCX resume — same check
- [ ] Upload a corrupted/empty file — confirm a clean 4xx error, not a crash
- [ ] Spot-check that no hallucinated content appears in the parsed output that wasn't in the source file

---

## Phase 4 — Conversational Resume Builder (LangGraph)

**Goal:** From free-text self-description to a confirmed, structured resume, via a recruiter-persona, clarifying-question-driven conversation.

- [ ] Design the LangGraph graph: `INTAKE → CLARIFYING (loop) → DRAFT_READY → AWAITING_CONFIRM → FINALIZED`
- [ ] System prompt: LLM must reason as a hiring recruiter/senior professional in the user's stated target field
- [ ] Clarifying-question logic: model decides when information is too vague/thin and asks a specific follow-up, rather than always asking a fixed set of questions
- [ ] Draft generation into the resume schema once enough information is gathered
- [ ] `AWAITING_CONFIRM` step: user can approve or request revisions (loop back to draft with feedback incorporated)
- [ ] `POST /resume-builder/start`, `POST /resume-builder/{run_id}/respond`, `POST /resume-builder/{run_id}/confirm` endpoints
- [ ] Persist graph state in `pipeline_runs.context` so a session can be resumed across requests

**Testing & Verification**
- [ ] Full manual run via Swagger UI: start a session with a deliberately vague self-description, confirm the system asks relevant clarifying questions (not generic ones)
- [ ] Confirm the draft is only shown after sufficient info is gathered, not prematurely
- [ ] Confirm requesting a revision at `AWAITING_CONFIRM` correctly loops back and updates the draft
- [ ] Confirm `FINALIZED` state persists the correct structured resume in the `resumes` table
- [ ] Test with two different target fields (e.g., backend engineer vs. a non-engineering role) — confirm the persona/questioning noticeably adapts

---

## Phase 5 — Resume Rendering (PDF Generation)

**Goal:** Structured resume JSON → a clean, ATS-friendly PDF.

- [ ] Jinja2 HTML template for resume layout (single clean template for v1)
- [ ] WeasyPrint conversion from rendered HTML to PDF
- [ ] `GET /resumes/{id}/pdf` endpoint returning the file
- [ ] Ensure output is plain-text-extractable (no ATS-hostile layouts — avoid tables/columns that break text extraction)

**Testing & Verification**
- [ ] Generate a PDF from a finalized resume, open it, visually confirm correct formatting
- [ ] Run the generated PDF through the Phase 3 parser (round-trip test) — confirm the extracted text is clean and matches the original content, proving it's ATS-extractable
- [ ] Test with a resume containing edge cases (long bullet lists, missing optional sections) — confirm no rendering crash

---

## Phase 6 — ATS Scoring Engine

**Goal:** Implement the scoring design from `ARCHITECTURE.md` Section 5, exposed for both specific-JD and generic-role checks.

- [ ] `app/services/ats_scoring.py`: keyword extraction (LLM), coverage scoring, embedding similarity (`sentence-transformers`), combined weighted score
- [ ] `POST /ats/score-against-jd` (resume_id + JD text) → score + breakdown
- [ ] `POST /ats/score-against-role` (resume_id + role + seniority) → synthesizes an "ideal JD" via LLM, then reuses the same scorer
- [ ] Store results in `jd_analyses`
- [ ] Response always includes: numeric score, missing must-have terms, missing nice-to-have terms, one-line semantic-fit comment — never a bare number

**Testing & Verification**
- [ ] Score a strong, well-matched resume against a JD — confirm a high score and a short/empty gap list
- [ ] Score a mismatched resume (e.g., a frontend-heavy resume against a backend JD) — confirm a low score with an accurate, specific gap list
- [ ] Confirm the generic-role path produces sensible synthetic JDs (manually review 2–3 generated "ideal JDs" for plausibility)
- [ ] Confirm scoring is deterministic enough that re-running the same resume+JD twice gives a consistent score (embedding similarity is deterministic; note if the LLM keyword-extraction step introduces variance, and pin temperature low if so)

---

## Phase 7 — JD-Aware Resume Tailoring (LangGraph)

**Goal:** Close the loop — score, identify gaps, ask the user, regenerate, re-score.

- [ ] LangGraph graph: `JD_PARSED → SCORED → GAP_REVIEW → AWAITING_GAP_CONFIRM → TAILORED → RESCORED`
- [ ] Senior-hiring-manager persona prompt: explain *why* each gap matters for this JD, not just that it's missing
- [ ] Per-gap user confirmation: system must never add a skill/claim the user hasn't explicitly confirmed
- [ ] Regeneration incorporates only confirmed additions, preserves everything else about the resume that was already strong
- [ ] Re-score after regeneration and store both scores for before/after comparison
- [ ] `POST /tailoring/start`, `POST /tailoring/{run_id}/confirm-gaps`, `GET /tailoring/{run_id}/result` endpoints

**Testing & Verification**
- [ ] Full manual run: take a real resume + real JD, confirm gap explanations are specific and JD-grounded (not generic advice)
- [ ] Confirm declining to add a gap (user says "no, I don't have that") results in that skill genuinely not appearing in the tailored resume
- [ ] Confirm the before/after score actually improves in a realistic test case
- [ ] Confirm previously-strong content isn't degraded or lost during regeneration (spot diff old vs. new resume)

---

## Phase 8 — Job Search Aggregator

**Goal:** Preference-driven job search across legitimate aggregator APIs, ranked by ATS match.

- [ ] Integrations: Adzuna, JSearch (RapidAPI), RemoteOK, Arbeitnow — one client module per source, normalized into a common internal listing shape
- [ ] `POST /jobs/search` accepting role, experience, location, job type, work mode, expected CTC — persists to `job_search_prefs`, queues an async search task
- [ ] Background worker (Arq/Celery) fetches from all sources, dedupes, stores in `job_listings`
- [ ] For each returned listing, run the ATS Scoring Engine (Phase 6) against the user's current resume, attach the score
- [ ] `GET /jobs/search/{run_id}/results` returns listings ranked by score
- [ ] Respect each API's free-tier rate limits; cache identical repeated queries

**Testing & Verification**
- [ ] Run a real search with realistic preferences (e.g., backend engineer, 1 YOE, hybrid, 15LPA+) — confirm real, relevant listings come back
- [ ] Confirm listings are ranked correctly by ATS score (spot-check top vs. bottom result)
- [ ] Confirm a search with unrealistic/narrow preferences degrades gracefully (empty list, not an error)
- [ ] Confirm repeated identical searches hit the cache, not the live API, within the cache window
- [ ] Confirm no direct LinkedIn/Indeed/Naukri requests exist anywhere in this phase's code

---

## Phase 9 — Interview Prep Generator

**Goal:** Turn gap-analysis data already collected into useful interview prep.

- [ ] `POST /interview-prep/{jd_analysis_id}` — generates likely interview questions + talking points from the stored gap breakdown
- [ ] Output grounded specifically in the JD and the resume's actual gaps/strengths, not generic questions
- [ ] Store generated prep alongside the `jd_analyses` record it came from

**Testing & Verification**
- [ ] Generate prep for a real JD analysis — confirm questions reference specifics from that JD (not boilerplate)
- [ ] Confirm talking points reference the user's actual resume content where relevant (i.e., it's using both sides of the gap, not just the JD)

---

## Phase 10 — Auto-Fill Draft (Application Assistance)

**Goal:** Pre-fill (never submit) applications on company-hosted ATS career pages.

- [ ] Detect ATS platform from a job listing URL/DOM (Greenhouse, Lever, Workday, Ashby, SmartRecruiters — start with 1–2, expand later)
- [ ] Playwright automation: navigate to the application form, map resume/profile fields to form fields per platform template
- [ ] Fill the form, take a screenshot of the filled state, **stop before any submit action**
- [ ] `POST /autofill/{listing_id}/draft` triggers the fill; response includes confirmation that no submission occurred
- [ ] Explicit safeguard in code: no code path in this module may click a submit/apply button — this should be enforced structurally, not just by convention

**Testing & Verification**
- [ ] Run against a real, currently-open listing on one supported ATS platform — confirm fields are filled correctly and no submission occurs
- [ ] Confirm the CAPTCHA/login-wall case is handled gracefully (pauses, reports status, doesn't crash or infinite-retry)
- [ ] Manually verify (read the code) that there is no reachable path to an automated submit action

---

## Phase 11 — Full Pipeline Orchestration ("Automation Mode")

**Goal:** Chain everything into one orchestrated flow with the same human checkpoints as the standalone features.

- [ ] `POST /pipeline/run` — given a target role/preferences, orchestrates: resume build/confirm (or use existing resume) → job search → per-job tailor + score → ranked shortlist with interview prep → auto-fill drafts for user-selected listings
- [ ] Pipeline pauses at every `AWAITING_*` state exactly as the standalone endpoints do — no shortcut that skips a confirmation
- [ ] `GET /pipeline/{run_id}/status` reports current step clearly
- [ ] End-to-end resumability: if the process is interrupted, the pipeline can resume from its last persisted state

**Testing & Verification**
- [ ] Run the full pipeline start-to-finish manually via Swagger UI for one realistic scenario, confirming every checkpoint pauses as expected and resumes correctly after input
- [ ] Kill and restart the app mid-pipeline (after a confirmation step) — confirm it resumes from the correct state, not from scratch
- [ ] Confirm the final output (ranked, tailored, scored shortlist with prep and optional draft applications) is coherent end-to-end

---

## Phase 12 — Hardening & Polish

**Goal:** Production-reasonable quality bar before calling this "done."

- [ ] Structured logging on every pipeline state transition
- [ ] Rate limiting on public-facing endpoints
- [ ] Auth enforced on all user-data endpoints (JWT)
- [ ] `.env.example` fully up to date with every var actually used
- [ ] README with setup instructions verified by literally following them on a clean checkout
- [ ] Full `pytest` suite passes; note current coverage gaps honestly rather than silently skipping

**Testing & Verification**
- [ ] Fresh clone + follow README setup instructions exactly — confirm the app comes up with no undocumented steps
- [ ] Full test suite run, all green
- [ ] Manually attempt to hit a protected endpoint without auth — confirm it's rejected
- [ ] Manually exceed the rate limit on one endpoint — confirm it's enforced

---

## Note on git hygiene (applies to every phase)

Do not include `Co-authored-by` trailers referencing any AI assistant in commit messages. Commit as the project owner only. If commits are made through an AI coding tool that adds such trailers automatically, strip them before or immediately after committing.
