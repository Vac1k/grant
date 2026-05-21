# AI Grant Matching Tool

AI Grant Matching Tool is an internal web tool for discovering, normalizing, and matching grant opportunities with client or project profiles.

The goal is to reduce manual grant research work. The implemented MVP collects grant data, stores raw snapshots, extracts structured features, compares grants with client profiles, accounts for previous application history, explains top matches, and shows the results in an internal dashboard.

## MVP Scope

The first MVP focuses on these grant sources:

- EU Funding & Tenders Portal
- Prostir grants
- GURT grants
- Diia Business finance programs

The MVP uses local structured files for client data:

- `CSV` client profiles
- separate `CSV` application history

Implemented stages mind map: [`docs/implemented_stages_mindmap.svg`](docs/implemented_stages_mindmap.svg).
Grant fields and extraction map: [`docs/grant_fields_extraction_map.uk.svg`](docs/grant_fields_extraction_map.uk.svg).

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
The day-to-day operations cheatsheet is [`docs/operations.md`](docs/operations.md).

After startup, the dashboard is available at:

- `http://localhost:8000/`
- `http://localhost:8000/grants`
- `http://localhost:8000/clients`
- `http://localhost:8000/matches`
- `http://localhost:8000/report`

## Ingestion

Stage 3 ingestion and Stage 5 feature extraction are available through the CLI:

```bash
docker compose exec app grant-tool ingest --all --limit 20
```

This collects up to 20 grants per MVP source, stores raw snapshots, runs deterministic feature extraction, upserts normalized grants, and records a `JobRun`.

To re-run Stage 5 extraction for already stored grants:

```bash
docker compose exec app grant-tool extract-features --limit 100
```

`--use-llm` is optional and only runs when `OPENAI_API_KEY` is configured. Without it, extraction stays deterministic and uses only source data already fetched from the real websites.

## Core Logic

The system follows this flow:

1. Collect raw grant data from configured sources.
2. Store raw snapshots for auditability.
3. Normalize grant fields: title, deadline, status, eligibility, applicant types, topics, funding amount, risks, and source URL.
4. Load client profiles and application history.
5. Match grants to clients using hard filters, keyword scoring, vector similarity, and application history boost.
6. Use an LLM to extract missing or unclear fields and explain top matches.
7. Show results in the dashboard report view.

Previous applications to similar grants are treated as a positive relevance signal regardless of outcome. `lost`, `rejected`, or `not_submitted` outcomes do not reduce the fit score, but they may create manual review notes.

## Tech Stack

- Backend: `FastAPI`
- API style: REST API first
- Dashboard: `Jinja2` + `HTMX`
- Database: `PostgreSQL` + `pgvector`
- ORM and migrations: `SQLAlchemy 2` + `Alembic`
- Jobs: CLI commands with `JobRun` audit records
- Broker/cache service in local stack: `Redis`
- AI provider: OpenAI
- Dependency management: Poetry
- Local runtime: Docker Compose
