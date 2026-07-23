You are building **CareerForge**, a backend-first AI system for resume building, ATS scoring, JD-aware resume tailoring, job search, interview prep, and application-drafting assistance.

Before writing any code, read these three files in full, in this order:
1. `PROJECT_SPEC.md` — what the system does, its core design principles, and what is explicitly out of scope. Treat the design principles in Section 5 as non-negotiable constraints on every feature you build, not suggestions.
2. `ARCHITECTURE.md` — the tech stack, system diagram, data schema, pipeline state machine, ATS scoring design, and repository structure. Follow this architecture; don't substitute a different stack or restructure the repo layout without telling me why first.
3. `DEVELOPMENT_ROADMAP.md` — the phased build plan. This is your primary execution guide.

## How to work

- **Build in phase order, exactly as listed in `DEVELOPMENT_ROADMAP.md`.** Do not skip ahead or combine phases, even if it seems more efficient — each phase is scoped so the app is in a fully working, testable state at its end.
- **Do not move to the next phase until the current phase's "Testing & Verification" checklist is fully satisfied.** Actually run the tests/checks listed — don't mark them done from inference. If something fails, fix it before proceeding, and tell me what broke and how you fixed it.
- **At the end of each phase**, give me a short status report: what was built, what you tested and the result, and explicit confirmation that the checklist is green. Then stop and wait for me to say "continue" before starting the next phase — don't auto-chain through all 12 phases in one go.
- **If anything in the three docs is ambiguous, underspecified, or you think a documented decision is actually a mistake, ask me before proceeding.** Don't silently guess on anything that affects data schema, security, or the core pipeline design. Small implementation details (variable names, internal function structure) are your call.
- **Never fabricate that something works.** If a live API call, a test, or a manual check wasn't actually run, say so explicitly rather than implying it passed.

## Non-negotiable constraints (repeating from PROJECT_SPEC.md because they matter)

- Every resume-producing or application-submitting action requires explicit human confirmation before finalizing — no auto-finalize, no auto-submit, anywhere, ever.
- Never invent skills, experience, or claims the user hasn't explicitly confirmed they have.
- No scraping or automation against LinkedIn, Indeed, Naukri, or any platform whose ToS prohibits it. Job search only uses the legitimate aggregator APIs named in `ARCHITECTURE.md`.
- The auto-fill feature (Phase 10) fills forms and stops — it must have no reachable code path to an automated submit action. Treat this as a hard safety requirement, not a soft guideline.
- Every ATS score must come with an explanation (missing terms, semantic-fit comment) — never return a bare number from that engine.
- Stick to free-tier services only (Gemini free tier, Adzuna, JSearch free tier, RemoteOK, Arbeitnow, Supabase/Neon, Upstash Redis). Flag it immediately if you hit a point where a feature genuinely requires a paid tier — don't silently build against a paid assumption.

## Git hygiene

Commit as the project owner. Do not add `Co-authored-by` trailers referencing any AI assistant to any commit message.

## Start

Confirm you've read all three docs, ask me anything that's unclear, then begin Phase 0.
