# CareerForge — Architecture

## 1. Tech stack (all free-tier compatible)

| Layer | Choice | Why |
|---|---|---|
| API framework | FastAPI (Python, async) | Auto-generated Swagger UI doubles as the interface — no frontend required to demo. |
| Orchestration (interactive flows) | LangGraph | Native support for multi-step agent workflows with checkpointing and human-in-the-loop interrupts — exactly the "draft → confirm → proceed" pattern this project needs. |
| Background jobs (job search, batch tailoring) | Arq (or Celery) + Redis | I/O-bound async work that shouldn't block API responses. |
| LLM | Google Gemini (free tier — Flash model) | Generous free quota, strong structured/JSON output support. |
| Embeddings | `sentence-transformers` (local, e.g. `all-MiniLM-L6-v2`) | Fully free, no API cost, no rate limit — runs on CPU. |
| Database | PostgreSQL (Supabase or Neon free tier) | Relational data: users, resumes, pipeline state, job listings. |
| Cache / Queue broker | Redis (Upstash free tier) | Session state, task queue, rate-limit counters. |
| Resume parsing (input) | `pdfplumber`, `python-docx` | Extract raw text from uploaded resumes. |
| Resume rendering (output) | Jinja2 templates + WeasyPrint | Structured JSON → HTML template → PDF. |
| Job listing sources | Adzuna API, JSearch (RapidAPI), RemoteOK API, Arbeitnow API | Legitimate free/freemium aggregator APIs — no LinkedIn/Indeed/Naukri scraping. |
| Auto-fill automation (later phase) | Playwright | Headless browser automation for company-hosted ATS forms (Greenhouse/Lever/Workday/Ashby/SmartRecruiters). |
| Auth | JWT (FastAPI OAuth2 password flow) | Simple, standard, no external auth provider dependency. |
| Migrations | Alembic | Schema versioning alongside SQLAlchemy models. |
| Hosting | Render / Railway / Fly.io (free tier) | API deployment. |
| Testing | Pytest + httpx (async test client) | Unit + integration tests per phase. |

No frontend is in scope for the initial build — FastAPI's `/docs` (Swagger UI) is the interface. This is a deliberate scope decision (see Project Spec, Section 6), not an oversight.

## 2. High-level system diagram

```
                          ┌─────────────────────────┐
                          │        FastAPI           │
                          │   (REST API + /docs)     │
                          └───────────┬──────────────┘
                                      │
        ┌─────────────────┬──────────┼───────────┬─────────────────┐
        │                  │          │           │                 │
┌───────▼──────┐  ┌────────▼───┐ ┌────▼─────┐ ┌───▼──────────┐ ┌────▼─────────┐
│ Resume Builder│  │ ATS Scoring│ │ JD Tailor│ │ Job Search    │ │ Auto-Fill     │
│ (LangGraph)   │  │ Engine     │ │(LangGraph)│ │ Aggregator    │ │ (Playwright)  │
└───────┬───────┘  └─────┬──────┘ └────┬─────┘ └──────┬────────┘ └──────┬───────┘
        │                │             │              │                 │
        └────────┬───────┴──────┬──────┴───────┬──────┴────────┬────────┘
                  │              │              │               │
           ┌──────▼───┐   ┌──────▼─────┐  ┌─────▼──────┐  ┌─────▼──────┐
           │ Gemini    │   │ sentence-  │  │  Redis      │  │ PostgreSQL │
           │ (LLM)     │   │ transformers│  │ (queue/    │  │ (state,    │
           │           │   │ (embeddings)│  │  cache)    │  │  data)     │
           └───────────┘   └────────────┘  └────────────┘  └────────────┘
```

## 3. Core data schema (structured resume representation)

Every feature reads/writes this shape — parser, builder, tailoring, and rendering all operate on it, not on raw text:

```json
{
  "contact": { "name": "", "email": "", "phone": "", "location": "", "links": [] },
  "summary": "",
  "skills": { "languages": [], "frameworks": [], "tools": [], "cloud_devops": [] },
  "experience": [
    {
      "company": "", "title": "", "start_date": "", "end_date": "",
      "bullets": ["quantified, action-verb-led achievement strings"]
    }
  ],
  "projects": [
    { "name": "", "description": "", "tech_stack": [], "link": "" }
  ],
  "education": [ { "institution": "", "degree": "", "dates": "" } ],
  "certifications": []
}
```

## 4. Pipeline state machine

Modeled as a `pipeline_run` row (Postgres) with `current_step`, `status`, and a JSON `context` blob. Each transition is an API call; steps requiring human input simply wait in that state until the corresponding "confirm" endpoint is called.

```
Resume creation:
  INTAKE → CLARIFYING → DRAFT_READY → AWAITING_CONFIRM → FINALIZED

JD-aware alteration:
  JD_PARSED → SCORED → GAP_REVIEW → AWAITING_GAP_CONFIRM → TAILORED → RESCORED

Job search (async):
  SEARCH_QUEUED → RESULTS_READY

Auto-fill (later phase):
  DRAFT_FILLED → AWAITING_SUBMIT_CONFIRM → (user submits manually, outside the system)

Full automation mode chains the above, pausing at every AWAITING_* state exactly as it would standalone.
```

LangGraph is used to implement the two interactive graphs (resume creation, JD-aware alteration) since it has native support for exactly this pause/resume/checkpoint pattern. Job search and auto-fill run as background tasks triggered by, and reporting status back into, the same `pipeline_run` record.

## 5. ATS Scoring Engine — design detail

1. Extract must-have and nice-to-have terms from the JD via an LLM call with a constrained JSON output schema (`{"must_have": [...], "nice_to_have": [...]}`).
2. Compute keyword coverage: for each term, check presence (and rough frequency) in the resume text — weight must-have terms higher than nice-to-have.
3. Compute embedding similarity: embed full resume text and full JD text with `sentence-transformers`, cosine similarity.
4. Combine into a single 0–100 score with a documented, fixed weighting (e.g., 60% keyword coverage, 40% semantic similarity — tune during Phase 6 testing, but keep the formula explicit and stable so before/after comparisons are meaningful).
5. Always return the score **plus** a structured breakdown: which must-have terms are missing, which are present, and a one-line semantic-fit comment. Never return a bare number from this engine.

## 6. External services & free-tier setup notes

- **Gemini API key**: obtain from Google AI Studio, free tier. Store as `GEMINI_API_KEY` env var.
- **Adzuna**: free developer account, `ADZUNA_APP_ID` + `ADZUNA_APP_KEY`.
- **JSearch (RapidAPI)**: free tier has a monthly request cap — build in caching so repeated identical searches don't burn quota.
- **RemoteOK / Arbeitnow**: no key required, fully open.
- **Supabase/Neon**: free Postgres instance, connection string as `DATABASE_URL`.
- **Upstash Redis**: free tier, connection string as `REDIS_URL`.

All keys live in a `.env` file (never committed — `.gitignore` this from Phase 0 onward).

## 7. Repository structure (proposed)

```
careerforge/
├── app/
│   ├── main.py                # FastAPI app entrypoint
│   ├── api/                   # route modules per feature
│   │   ├── resume.py
│   │   ├── ats.py
│   │   ├── tailoring.py
│   │   ├── jobs.py
│   │   ├── interview_prep.py
│   │   ├── autofill.py
│   │   └── pipeline.py
│   ├── core/                  # config, security, db session
│   ├── models/                # SQLAlchemy models
│   ├── schemas/                # Pydantic schemas (incl. the resume JSON schema)
│   ├── graphs/                 # LangGraph state graphs
│   │   ├── resume_builder_graph.py
│   │   └── jd_tailoring_graph.py
│   ├── services/
│   │   ├── llm_client.py
│   │   ├── embeddings.py
│   │   ├── ats_scoring.py
│   │   ├── resume_parser.py
│   │   ├── resume_renderer.py
│   │   ├── job_search.py
│   │   └── autofill/           # Playwright ATS-platform templates
│   └── workers/                 # Arq/Celery task definitions
├── tests/                       # mirrors app/ structure
├── alembic/
├── .env.example
├── requirements.txt
└── README.md
```

## 8. Non-functional requirements

- Every LLM call must have retry-with-backoff and a graceful failure path (never silently return an empty resume).
- Every external API call (job search, LLM, embeddings) must be timeout-bounded.
- All endpoints documented via FastAPI's automatic OpenAPI schema — no undocumented routes.
- Logging on every pipeline state transition (for debugging and, later, an audit trail).
