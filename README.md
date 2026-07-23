# CareerForge

A backend-first AI system that builds, scores, and tailors resumes against real job descriptions, finds matching job openings, preps candidates for interviews based on the gaps it finds, and (later) drafts — but never auto-submits — job applications on company career pages.

See [`PROJECT_SPEC.md`](PROJECT_SPEC.md) for what this does and why, [`ARCHITECTURE.md`](ARCHITECTURE.md) for the tech stack and system design, and [`DEVELOPMENT_ROADMAP.md`](DEVELOPMENT_ROADMAP.md) for the phased build plan and current progress.

No frontend is in scope yet — FastAPI's auto-generated Swagger UI (`/docs`) is the interface.

## Status

Currently in **Phase 0 — Project Scaffolding & Environment**. See `DEVELOPMENT_ROADMAP.md` for the full phase-by-phase checklist.

## Tech stack

FastAPI, LangGraph, PostgreSQL, Redis, Google Gemini, `sentence-transformers`. Full rationale in `ARCHITECTURE.md`.

## Running locally (Docker Compose)

The app, PostgreSQL, and Redis all run as containers — this avoids installing native dependencies (e.g. WeasyPrint's GTK/Pango/Cairo libraries) directly on your machine.

**Prerequisites:** Docker Desktop (or Docker Engine + Compose).

1. Copy the env template and fill in whichever API keys you already have (blank keys are fine until the phase that needs them):
   ```
   cp .env.example .env
   ```
2. Build and start the stack:
   ```
   docker compose up --build
   ```
3. The API is now available at `http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`.
4. Check `GET /health` — it reports API, database, and Redis connectivity status.

Postgres is exposed on host port `5433` and Redis on `6380` (mapped to avoid clashing with any local installs), in case you want to connect a DB client directly.

### Common commands

Run these against the running `app` container:

```
docker compose exec app alembic upgrade head      # apply migrations
docker compose exec app alembic downgrade base    # roll back all migrations
docker compose exec app pytest                    # run the test suite
```

## Environment variables

See [`.env.example`](.env.example) for the full list with descriptions. Required from Phase 0 onward: `DATABASE_URL`, `REDIS_URL`. Feature-specific keys (Gemini, Adzuna, JSearch) are only needed once the phase that uses them is reached.

## Project layout

See `ARCHITECTURE.md` Section 7 for the full repository structure and rationale.

## Non-negotiable design principles

This project follows a strict set of constraints — no auto-finalized or auto-submitted resumes/applications without explicit human confirmation, no fabricated experience, no ToS-violating scraping, free-tier infrastructure only. See `PROJECT_SPEC.md` Section 5 for the full list.
