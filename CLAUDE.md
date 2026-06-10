# CLAUDE.md

Guidance for Claude Code and other AI coding agents working in this repository.

## Project

AI Grant Matching Tool is an internal web tool for collecting, normalizing, matching, and explaining grant opportunities against client or project profiles.

The MVP pipeline:

1. Ingests grant listings and detail pages from configured sources.
2. Stores discovered item-level results and raw snapshots for auditability.
3. Extracts normalized grant fields.
4. Imports client profiles and prior application history.
5. Scores grant-client matches using filters, keywords, vectors, and history boosts.
6. Generates deterministic or OpenAI-backed explanations.
7. Shows results in the FastAPI/Jinja2/HTMX dashboard.

## Repository Layout

- `grant_tool/`: application package.
- `grant_tool/main.py`: FastAPI application entry point.
- `grant_tool/cli.py`: `grant-tool` CLI commands.
- `grant_tool/db/`: SQLAlchemy models, session, repositories.
- `grant_tool/ingestion/`: source connectors and ingestion orchestration.
- `grant_tool/extraction/`: feature extraction and optional LLM enrichment.
- `grant_tool/embeddings/`: hash and OpenAI embedding providers.
- `grant_tool/matching/`: matching logic.
- `grant_tool/explanations/`: deterministic and OpenAI explanation providers.
- `grant_tool/dashboard/`: dashboard routes and service code.
- `migrations/`: Alembic migrations.
- `data/manual_seed/`: manual seed CSV files.
- `docs/`: operational and product documentation.
- `tests/`: test suite.

## Tech Stack

- Python 3.12+
- FastAPI
- Jinja2 + HTMX
- PostgreSQL + pgvector
- SQLAlchemy 2 + Alembic
- Redis in the local Docker stack
- Poetry for dependency management
- Docker Compose for local runtime
- OpenAI is optional and only needed for explicit OpenAI-backed commands.

## Local Commands

Run commands from the repository root:

```bash
cd /Users/vac1k/Projects/ai_replace_grandwriters/grant
```

Start the full local stack:

```bash
docker compose up --build
```

Start in the background:

```bash
docker compose up -d --build
```

Stop without deleting PostgreSQL data:

```bash
docker compose down
```

Delete local PostgreSQL data only when explicitly intended:

```bash
docker compose down -v
```

Dashboard URLs:

```text
http://localhost:8000/
http://localhost:8000/grants
http://localhost:8000/clients
http://localhost:8000/matches
http://localhost:8000/report
http://localhost:8000/api/v1/health
http://localhost:8000/docs
```

## Smoke Flow

Use local deterministic providers unless the task specifically requires OpenAI:

```bash
docker compose exec app grant-tool import-manual-seed
docker compose exec app grant-tool ingest --all --limit 20 --mode incremental
docker compose exec app grant-tool extract-features --limit 100
docker compose exec app grant-tool deduplicate
docker compose exec app grant-tool quality-score
docker compose exec app grant-tool embed --target all --provider hash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
docker compose exec app grant-tool explain-matches --limit 20 --provider rule
```

Quality checks:

```bash
docker compose exec app grant-tool search-report
docker compose exec app grant-tool quality-gate
docker compose exec app grant-tool data-audit
docker compose exec app grant-tool quality-score --dry-run
```

Grant quality data layer:

- `grants.quality_score` (0-100), `grants.quality_tier`, and `grants.quality_flags` are persisted by `extract-features`, `deduplicate`, and `quality-score`; the explainable breakdown lives in `extraction_metadata.quality`.
- Matching excludes records with persisted score below the threshold unless `grant-tool match --include-low-quality` is used.
- There is no separate prepared-grants table; the prepared set is `GrantRepository.list_prepared_grants` plus the dashboard quality filter.

Jobs:

```bash
docker compose exec app grant-tool jobs list
docker compose exec app grant-tool jobs list --type ingestion
docker compose exec app grant-tool jobs show <job-id>
```

Database:

```bash
docker compose exec app alembic upgrade head
docker compose exec app grant-tool seed-sources
docker compose exec db psql -U grant -d grant
```

## Tests

Prefer the project test suite before finishing behavior changes:

```bash
poetry run pytest
```

For Docker-based verification, use:

```bash
docker compose exec app pytest
```

## Source Connectors

Currently implemented production connectors include:

- `eu-funding`
- `prostir`
- `diia-business`
- `chas-zmin`
- `eufundingportal-eu`
- `hromady`
- `nipo`
- `grant-market`
- `fundsforngos`
- `opportunitydesk`
- `grantforward`

`gurt` has a local connector, but live production validation can be blocked by Cloudflare/human-check. Do not try to bypass that protection. Document the limitation instead.

`grantsense` is deferred because validation did not find a stable public direct opportunity feed.

For `grantforward`, keep ingestion limits low, usually `--limit 10`; the public search endpoint exposes only the first page without login.

## Environment

Local Docker defaults:

```text
APP_ENV=local
DATABASE_URL=postgresql+psycopg://grant:grant@db:5432/grant
REDIS_URL=redis://redis:6379/0
```

Optional OpenAI settings:

```text
OPENAI_API_KEY=
LLM_MODEL=gpt-4.1-mini
EMBEDDING_MODEL=text-embedding-3-small
HTTP_USER_AGENT=AIGrantMatchingTool/0.1 (+local MVP)
```

`OPENAI_API_KEY` is required only for:

- `grant-tool extract-features --use-llm`
- `grant-tool embed --provider openai`
- `grant-tool explain-matches --provider openai`

## Development Rules

- Preserve raw snapshots and audit fields when changing ingestion or extraction logic.
- Keep source-specific parsing isolated in connector code.
- Prefer deterministic providers (`hash`, `rule`) for local tests and smoke checks.
- Treat prior application history as a positive relevance signal. Negative outcomes such as `lost`, `rejected`, or `not_submitted` should not reduce fit score, though they may create manual review notes.
- Do not use `docker compose down -v` unless the user explicitly wants local DB data removed.
- Do not bypass source anti-bot, login, or human-check protections.
- Use Alembic migrations for schema changes.
- Keep documentation in sync when changing commands, source behavior, or pipeline stages.
