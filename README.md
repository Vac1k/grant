# AI Grant Matching Tool

AI Grant Matching Tool is an internal web tool for discovering, normalizing, and matching grant opportunities with client or project profiles.

The goal is to reduce manual grant research work. The system will collect new and updated grants, extract structured features, compare them with client profiles, account for previous application history, and generate clear reports with top matches, risks, and manual review notes.

## MVP Scope

The first MVP focuses on these grant sources:

- EU Funding & Tenders Portal
- Prostir grants
- GURT grants
- Diia Business finance programs

The first version uses local structured files for client data:

- `CSV` client profiles
- separate `CSV` application history
- Google Drive integration is deferred to a later stage

## Core Logic

The system follows this flow:

1. Collect raw grant data from configured sources.
2. Store raw snapshots for auditability.
3. Normalize grant fields: title, deadline, status, eligibility, applicant types, topics, funding amount, risks, and source URL.
4. Load client profiles and application history.
5. Match grants to clients using hard filters, keyword scoring, vector similarity, and application history boost.
6. Use an LLM to extract missing or unclear fields and explain top matches.
7. Show results in the dashboard and daily report.

Previous applications to similar grants are treated as a positive relevance signal regardless of outcome. `lost`, `rejected`, or `not_submitted` outcomes do not reduce the fit score, but they may create manual review notes.

## Tech Stack

- Backend: `FastAPI`
- API style: REST API first
- Dashboard: `Jinja2` + `HTMX`
- Database: `PostgreSQL` + `pgvector`
- ORM and migrations: `SQLAlchemy 2` + `Alembic`
- Jobs: `Celery` + `Redis`
- AI provider: OpenAI
- Dependency management: Poetry
- Local runtime: Docker Compose

## Current Status

Stage 1 is complete.

Implemented:

- Python package structure: `grant_tool`
- FastAPI app
- root endpoint: `/`
- health endpoint: `/api/v1/health`
- Poetry dependencies and `poetry.lock`
- Dockerfile
- Docker Compose setup
- PostgreSQL with `pgvector`
- Redis
- Celery worker and scheduler placeholders via Docker Compose profiles
- `.env.example`
- `.dockerignore`
- startup documentation in `docs/start.md`

Verified:

- `docker compose up --build -d`
- `docker compose ps`
- `curl http://localhost:8000/api/v1/health`
- `curl -I http://localhost:8000/docs`
- `docker compose down`

## Local Start

Docker Compose is the primary way to run the project locally.

Detailed startup commands are documented here:

- [docs/start.md](docs/start.md)

First local setup:

```bash
cp .env.example .env
docker compose up --build
```

API endpoints:

- app: `http://localhost:8000`
- health: `http://localhost:8000/api/v1/health`
- OpenAPI docs: `http://localhost:8000/docs`

Stop services:

```bash
docker compose down
```

## Documentation

Project planning:

- [planning/plan.md](planning/plan.md)
- [planning/step1_stages.md](planning/step1_stages.md)
- [planning/technologies.md](planning/technologies.md)

Runtime documentation:

- [docs/start.md](docs/start.md)

## Next Stage

Next implementation stage: Stage 2, data model and database layer.

Stage 2 should add:

- SQLAlchemy models
- Alembic migrations
- database session management
- repository/service layer
- tables for sources, raw grants, normalized grants, client profiles, application history, match runs, matches, and reports
