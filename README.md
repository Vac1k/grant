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

## Local Start

The normal local workflow is one Docker Compose command:

```bash
docker compose up --build
```

Compose starts PostgreSQL, Redis, a one-shot `migrate` service, and the FastAPI app.
The `migrate` service runs database migrations and seeds the MVP sources:

```bash
alembic upgrade head
grant-tool seed-sources
```

Use `docker compose down` to stop containers without deleting database data.
Use `docker compose down -v` only when you want to delete the local PostgreSQL volume.

Detailed commands live in [`docs/start.md`](docs/start.md).

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
