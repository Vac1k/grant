# App Operations Cheatsheet

This file contains the commands used during Stage 2-9 implementation and testing.
Run all commands from the project directory:

```bash
cd /Users/vac1k/Projects/ai_replace_grandwriters/grant
```

## Start The App

Build and start everything:

```bash
docker compose up -d --build
```

Start everything without rebuilding:

```bash
docker compose up -d
```

Watch logs:

```bash
docker compose logs -f app
```

Check running containers:

```bash
docker compose ps
```

Stop containers but keep database data:

```bash
docker compose down
```

Stop containers and delete Docker volumes, including PostgreSQL data:

```bash
docker compose down -v
```

Important: normal `docker compose down` does not delete DB data. `docker compose down -v` deletes the database volume.

## Database And Migrations

Apply migrations from inside Docker:

```bash
docker compose exec app alembic upgrade head
```

Seed/update configured MVP sources:

```bash
docker compose exec app grant-tool seed-sources
```

Open psql:

```bash
docker compose exec db psql -U grant -d grant
```

## Clean Grant Data Before Retesting Stage 5

These commands delete only grant ingestion/matching data, not client profiles and not imported application history.

```bash
docker compose exec db psql -U grant -d grant -c "delete from grant_client_matches;"
docker compose exec db psql -U grant -d grant -c "delete from grants;"
docker compose exec db psql -U grant -d grant -c "delete from raw_grant_snapshots;"
docker compose exec db psql -U grant -d grant -c "delete from job_runs where job_type = 'ingestion';"
```

Meaning:

- `grant_client_matches`: deletes calculated matches between clients and grants.
- `grants`: deletes normalized grants.
- `raw_grant_snapshots`: deletes raw HTML/API payload snapshots saved during ingestion.
- `job_runs where job_type = 'ingestion'`: deletes ingestion job history only.

If foreign key constraints ever block deletion, use this order first:

```bash
docker compose exec db psql -U grant -d grant -c "delete from grant_client_matches;"
docker compose exec db psql -U grant -d grant -c "delete from raw_grant_snapshots;"
docker compose exec db psql -U grant -d grant -c "delete from grants;"
docker compose exec db psql -U grant -d grant -c "delete from job_runs where job_type = 'ingestion';"
```

## Ingest Real Grant Data

Ingest all MVP sources, max 20 records per source:

```bash
docker compose exec app grant-tool ingest --all --limit 20
```

Ingest only one source:

```bash
docker compose exec app grant-tool ingest --source prostir --limit 20
docker compose exec app grant-tool ingest --source gurt --limit 20
docker compose exec app grant-tool ingest --source eu-funding --limit 20
docker compose exec app grant-tool ingest --source diia-business --limit 20
```

Diia Business uses the public frontend API:

```text
https://api.business.diia.gov.ua/api/front/finance
```

This gives better fields than HTML scraping because Diia pages are Angular shells and the visible content is loaded by JavaScript.

## Run Stage 5 Feature Extraction

Deterministic extraction only:

```bash
docker compose exec app grant-tool extract-features --limit 100
```

Optional LLM extraction:

```bash
docker compose exec app grant-tool extract-features --limit 100 --use-llm
```

`--use-llm` only works when `OPENAI_API_KEY` is configured. Without `--use-llm`, the app uses deterministic parsing only.

## Run Stage 6/7 Matching

Run strict Stage 6 shortlist matching:

```bash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20
```

Generate Stage 7 embeddings with the deterministic local provider:

```bash
docker compose exec app grant-tool embed --target all --provider hash
```

Generate real semantic embeddings with OpenAI:

```bash
docker compose exec app grant-tool embed --target all --provider openai
```

Run matching with vector similarity enabled:

```bash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
```

`hash` embeddings are only for local smoke tests and repeatable unit tests. Use `openai` embeddings for real semantic matching quality.

Check embedding coverage:

```bash
docker compose exec db psql -U grant -d grant -c "select 'grants' target, count(*) total, count(embedding) embedded from grants union all select 'clients', count(*), count(embedding) from client_profiles union all select 'history', count(*), count(embedding) from application_history;"
```

Check latest matches:

```bash
docker compose exec db psql -U grant -d grant -c "select c.slug client, m.rank, m.score, m.keyword_score, m.vector_score, m.history_score, left(g.title, 90) grant_title from grant_client_matches m join client_profiles c on c.id=m.client_profile_id join grants g on g.id=m.grant_id order by m.created_at desc, c.slug, m.rank limit 20;"
```

## Run Stage 8 Match Explanations

Generate deterministic local explanations for smoke testing:

```bash
docker compose exec app grant-tool explain-matches --limit 20 --provider rule
```

Generate real LLM explanations with OpenAI:

```bash
docker compose exec app grant-tool explain-matches --limit 20 --provider openai
```

Generate explanations for one exact match run:

```bash
docker compose exec app grant-tool explain-matches --match-run-id <match-run-id> --limit 20 --provider openai
```

`--provider openai` requires `OPENAI_API_KEY` in `.env`. The model is controlled by `LLM_MODEL`.

Stage 8 writes explanations to `grant_client_matches`:

- `explanation`
- `risks_text`
- `manual_checks`
- `llm_score`
- `match_metadata.llm_explanation`

Check saved explanations:

```bash
docker compose exec db psql -U grant -d grant -c "select c.slug client, m.rank, m.score, m.llm_score, left(g.title, 80) grant_title, left(m.explanation, 180) explanation, left(m.risks_text, 180) risks from grant_client_matches m join client_profiles c on c.id=m.client_profile_id join grants g on g.id=m.grant_id where m.explanation is not null order by m.updated_at desc limit 20;"
```

## Open Stage 9 Dashboard

After `docker compose up`, open:

```text
http://localhost:8000/
```

Dashboard pages:

```text
http://localhost:8000/
http://localhost:8000/grants
http://localhost:8000/clients
http://localhost:8000/matches
http://localhost:8000/report
```

Quick HTTP smoke:

```bash
curl -s -o /tmp/grant_dashboard_home.html -w "%{http_code} %{content_type}\n" http://localhost:8000/
curl -s -o /tmp/grant_dashboard_grants.html -w "%{http_code} %{content_type}\n" http://localhost:8000/grants
curl -s -o /tmp/grant_dashboard_css.css -w "%{http_code} %{content_type}\n" http://localhost:8000/static/css/dashboard.css
```

Expected result: `200 text/html` for pages and `200 text/css` for CSS.

## Inspect Saved Grant Fields

Show recent grants:

```bash
docker compose exec db psql -U grant -d grant -c "select g.title, g.status, g.support_type, g.funding_amount_text, g.currency, g.deadline_text, g.funder_name, g.geography_text from grants g order by g.updated_at desc limit 20;"
```

Show grants by source:

```bash
docker compose exec db psql -U grant -d grant -c "select s.slug, g.title, g.status, g.support_type, g.funding_amount_text, g.currency, g.deadline_text from grants g join sources s on s.id = g.source_id order by s.slug, g.title limit 50;"
```

Show Diia grants only:

```bash
docker compose exec db psql -U grant -d grant -c "select g.title, g.status, g.support_type, g.funding_amount_text, g.currency, g.deadline_text, g.funder_name, g.geography_text from grants g join sources s on s.id = g.source_id where s.slug = 'diia-business' order by g.updated_at desc limit 20;"
```

Show raw snapshots for a source:

```bash
docker compose exec db psql -U grant -d grant -c "select s.slug, r.source_url, r.http_status, r.content_type, length(coalesce(r.raw_text, '')) as raw_text_len from raw_grant_snapshots r join sources s on s.id = r.source_id order by r.fetched_at desc limit 20;"
```

## Check Whether LLM Was Used

Check extraction methods stored on grants:

```bash
docker compose exec db psql -U grant -d grant -c "select extraction_method, count(*) from grants group by extraction_method order by extraction_method;"
```

If LLM was used successfully, you should see `deterministic_llm`.
If only deterministic extraction was used, you should see `deterministic`.

Check feature extraction job metadata:

```bash
docker compose exec db psql -U grant -d grant -c "select job_type, job_metadata->>'use_llm' as use_llm, status, started_at, finished_at from job_runs where job_type = 'feature_extraction' order by started_at desc limit 20;"
```

## Run Tests

Local tests:

```bash
poetry run python -m unittest
poetry run python -m compileall grant_tool tests
```

Docker tests:

```bash
docker compose exec app python -m unittest
```

## Typical Full Retest Flow

```bash
docker compose up -d --build
docker compose exec app alembic upgrade head
docker compose exec app grant-tool seed-sources
docker compose exec db psql -U grant -d grant -c "delete from grant_client_matches;"
docker compose exec db psql -U grant -d grant -c "delete from grants;"
docker compose exec db psql -U grant -d grant -c "delete from raw_grant_snapshots;"
docker compose exec db psql -U grant -d grant -c "delete from job_runs where job_type = 'ingestion';"
docker compose exec app grant-tool ingest --all --limit 20
docker compose exec app grant-tool extract-features --limit 100
docker compose exec app grant-tool embed --target all --provider hash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
docker compose exec app grant-tool explain-matches --limit 20 --provider rule
docker compose exec db psql -U grant -d grant -c "select s.slug, g.title, g.status, g.support_type, g.funding_amount_text, g.currency, g.deadline_text from grants g join sources s on s.id = g.source_id order by s.slug, g.title limit 50;"
```
