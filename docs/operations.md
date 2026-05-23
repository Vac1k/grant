# Операційна Пам'ятка

Усі команди запускати з директорії проєкту:

```bash
cd /Users/vac1k/Projects/ai_replace_grandwriters/grant
```

Проєкт зараз реалізований до Stage 9:

- Stage 1/2: FastAPI, Docker Compose, PostgreSQL/pgvector, SQLAlchemy, Alembic.
- Stage 2.5: seed джерел і tracking через `JobRun`.
- Stage 3: ingestion MVP-джерел EU Funding, Prostir, Diia Business і GURT.
- Stage Search Step 4.1/4.2/4.3: додаткові конектори під окремі джерела для Chas Zmin, EUFundingPortal.eu, Hromady, NIPO, Grant Market, fundsforNGOs і Opportunity Desk.
- Stage 4: імпорт ручних CSV для client profiles і application history.
- Stage 5: deterministic feature extraction з optional OpenAI LLM enrichment.
- Stage 6: shortlist matching.
- Stage 7: embeddings через local hash або OpenAI providers.
- Stage 8: deterministic або OpenAI match explanations.
- Stage 9: dashboard pages для overview, grants, clients, matches і report view.

Mind map реалізованих stage-ів: [`implemented_stages_mindmap.svg`](implemented_stages_mindmap.svg).
Мапа grant fields і extraction: [`grant_fields_extraction_map.uk.svg`](grant_fields_extraction_map.uk.svg).

## Start The App

Build and start everything in the foreground:

```bash
docker compose up --build
```

Build and start everything in the background:

```bash
docker compose up -d --build
```

Start without rebuilding:

```bash
docker compose up -d
```

Compose starts `db`, `redis`, one-shot `migrate`, and `app`. The `migrate` service runs:

```bash
alembic upgrade head
grant-tool seed-sources
```

Watch app logs:

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

## Environment

Local configuration comes from `.env`.

Required for Docker local defaults:

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

`OPENAI_API_KEY` is only required for:

- `grant-tool extract-features --use-llm`
- `grant-tool embed --provider openai`
- `grant-tool explain-matches --provider openai`

## Database And Migrations

Apply migrations manually if needed:

```bash
docker compose exec app alembic upgrade head
```

Seed/update configured sources:

```bash
docker compose exec app grant-tool seed-sources
```

Open psql:

```bash
docker compose exec db psql -U grant -d grant
```

Show tables:

```bash
docker compose exec db psql -U grant -d grant -c "\dt"
```

Show current Alembic revision:

```bash
docker compose exec app alembic current
```

## Jobs

List all recent jobs:

```bash
docker compose exec app grant-tool jobs list
```

List jobs by type:

```bash
docker compose exec app grant-tool jobs list --type ingestion
docker compose exec app grant-tool jobs list --type import_clients
docker compose exec app grant-tool jobs list --type import_history
docker compose exec app grant-tool jobs list --type feature_extraction
docker compose exec app grant-tool jobs list --type embedding
docker compose exec app grant-tool jobs list --type llm_extraction
```

Show one job:

```bash
docker compose exec app grant-tool jobs show <job-id>
```

## Import Manual Client Data

Default manual seed files:

- `data/manual_seed/client_profiles.manual.csv`
- `data/manual_seed/application_history.manual.csv`
- `data/manual_seed/document_inventory.manual.csv`

Import client profiles and application history together:

```bash
docker compose exec app grant-tool import-manual-seed
```

Import only client profiles:

```bash
docker compose exec app grant-tool import-clients --file data/manual_seed/client_profiles.manual.csv
```

Import only application history:

```bash
docker compose exec app grant-tool import-application-history --file data/manual_seed/application_history.manual.csv
```

`document_inventory.manual.csv` is currently an operator reference file. It is not imported by the CLI.

Check imported clients:

```bash
docker compose exec db psql -U grant -d grant -c "select slug, name, country, organization_type, enabled from client_profiles order by slug;"
```

Check imported history:

```bash
docker compose exec db psql -U grant -d grant -c "select client_name, grant_title, result, similarity_weight from application_history order by client_name, grant_title limit 30;"
```

## Збір Реальних Даних Про Гранти

Зібрати всі налаштовані джерела, максимум 20 записів на джерело:

```bash
docker compose exec app grant-tool ingest --all --limit 20 --mode incremental
```

Зібрати одне джерело:

```bash
docker compose exec app grant-tool ingest --source eu-funding --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source prostir --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source diia-business --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source gurt --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source chas-zmin --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source eufundingportal-eu --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source hromady --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source nipo --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source grant-market --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source fundsforngos --limit 20 --mode incremental
docker compose exec app grant-tool ingest --source opportunitydesk --limit 20 --mode incremental
```

Режими:

- `incremental` перечитує listing/RSS/API/search endpoint, оновлює `last_seen_at` і пропускає detail-fetch для вже відомих item-level грантів;
- `backfill` перечитує listing/RSS/API/search endpoint і повторно робить detail-fetch навіть для відомих item-level грантів.

Перевірити Stage 1 discovery-таблицю:

```bash
docker compose exec db psql -U grant -d grant -c "select source_slug, discovery_status, detail_fetch_status, count(*) from discovered_grant_items group by source_slug, discovery_status, detail_fetch_status order by source_slug;"
```

Перевірити operational search report:

```bash
docker compose exec app grant-tool search-report
```

Перевірити Step 9 quality gate на мінімум 10 якісних grants для кожного implementable джерела, крім `gurt`:

```bash
docker compose exec app grant-tool quality-gate
```

Якщо потрібен тільки report без non-zero exit при blocked gate:

```bash
docker compose exec app grant-tool quality-gate --no-fail
```

Для production quality gate використовуй backfill limits, які реально дали 10 quality-approved records:

```bash
docker compose exec app grant-tool ingest --source eu-funding --limit 20 --mode backfill
docker compose exec app grant-tool ingest --source prostir --limit 20 --mode backfill
docker compose exec app grant-tool ingest --source diia-business --limit 20 --mode backfill
docker compose exec app grant-tool ingest --source chas-zmin --limit 20 --mode backfill
docker compose exec app grant-tool ingest --source eufundingportal-eu --limit 20 --mode backfill
docker compose exec app grant-tool ingest --source hromady --limit 50 --mode backfill
docker compose exec app grant-tool ingest --source nipo --limit 200 --mode backfill
docker compose exec app grant-tool ingest --source grant-market --limit 20 --mode backfill
docker compose exec app grant-tool ingest --source fundsforngos --limit 20 --mode backfill
docker compose exec app grant-tool ingest --source opportunitydesk --limit 20 --mode backfill
docker compose exec app grant-tool quality-gate
```

Нотатки реалізації:

- EU Funding використовує EU Funding & Tenders search API.
- Prostir використовує RSS discovery і HTML detail parsing.
- Diia Business використовує public frontend finance API, бо це якісніше за scraping Angular shell сторінок.
- GURT використовує HTML list/detail parsing.
- Chas Zmin, EUFundingPortal.eu, Hromady, NIPO і fundsforNGOs використовують WP REST search із RSS fallback.
- Grant Market використовує sitemap discovery з фільтром `/opp/` і HTML detail parsing.
- Opportunity Desk використовує WP REST search із category filter `Awards and Grants`, відкидає digest/list posts і має RSS fallback.
- NIPO використовує розширені WP REST search terms, включно з `SME Fund`, `премія`, `відбір`, `фінансування`, `відшкодування`, бо базові terms давали забагато news/digest content.
- NIPO, fundsforNGOs і Opportunity Desk позначають результати як `needs_manual_review`, бо ці джерела можуть містити дайджести, новини або широкий міжнародний noise.
- GrantSense поки не має production connector: live validation показала sitemap/service/category/blog pages і Next.js error shell без стабільного direct opportunity feed.
- GrantForward поки не має production connector: live validation показала search UI без direct result links у HTML, `404` для WP REST/RSS/sitemap і login/subscription mechanics.
- Ingestion спочатку зберігає item-level результат пошуку у `discovered_grant_items`.
- Raw detail payload зберігається у `raw_grant_snapshots`.
- Нормалізований грант записується або оновлюється у `grants`.
- Ingestion також запускає deterministic Stage 5 enrichment перед збереженням кожного гранту.

## Run Stage 5 Feature Extraction

Deterministic extraction only:

```bash
docker compose exec app grant-tool extract-features --limit 100
```

For one source:

```bash
docker compose exec app grant-tool extract-features --source prostir --limit 20
```

Optional LLM extraction:

```bash
docker compose exec app grant-tool extract-features --limit 100 --use-llm
```

`--use-llm` only works when `OPENAI_API_KEY` is configured. Without it, the app uses deterministic parsing only.

Check extraction methods:

```bash
docker compose exec db psql -U grant -d grant -c "select extraction_method, count(*) from grants group by extraction_method order by extraction_method;"
```

Check manual review volume:

```bash
docker compose exec db psql -U grant -d grant -c "select s.slug, count(*) total, count(*) filter (where g.needs_manual_review) manual_review from grants g join sources s on s.id = g.source_id group by s.slug order by s.slug;"
```

## Run Stage 6 Matching

Run strict shortlist matching:

```bash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20
```

Run for one client:

```bash
docker compose exec app grant-tool match --client 10guards --top-n 5 --min-score 0.20
```

Limit evaluated grants:

```bash
docker compose exec app grant-tool match --grant-limit 50 --top-n 5 --min-score 0.20
```

Check latest matches:

```bash
docker compose exec db psql -U grant -d grant -c "select c.slug client, m.rank, m.score, m.keyword_score, m.vector_score, m.history_score, left(g.title, 90) grant_title from grant_client_matches m join client_profiles c on c.id=m.client_profile_id join grants g on g.id=m.grant_id order by m.created_at desc, c.slug, m.rank limit 20;"
```

## Run Stage 7 Embeddings

Generate deterministic local embeddings:

```bash
docker compose exec app grant-tool embed --target all --provider hash
```

Generate embeddings for one target:

```bash
docker compose exec app grant-tool embed --target grants --provider hash
docker compose exec app grant-tool embed --target clients --provider hash
docker compose exec app grant-tool embed --target history --provider hash
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

Useful filters:

```text
http://localhost:8000/grants?source=prostir
http://localhost:8000/grants?manual_review=true
http://localhost:8000/grants?q=AI
http://localhost:8000/matches?min_score=0.3
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

Show raw snapshots:

```bash
docker compose exec db psql -U grant -d grant -c "select s.slug, r.source_url, r.http_status, r.content_type, length(coalesce(r.raw_text, '')) as raw_text_len from raw_grant_snapshots r join sources s on s.id = r.source_id order by r.fetched_at desc limit 20;"
```

## Clean Grant Data Before Retesting

These commands delete grant ingestion and matching data, but keep client profiles and imported application history.

```bash
docker compose exec db psql -U grant -d grant -c "delete from grant_client_matches;"
docker compose exec db psql -U grant -d grant -c "delete from match_runs;"
docker compose exec db psql -U grant -d grant -c "delete from raw_grant_snapshots;"
docker compose exec db psql -U grant -d grant -c "delete from grants;"
docker compose exec db psql -U grant -d grant -c "delete from discovered_grant_items;"
docker compose exec db psql -U grant -d grant -c "delete from job_runs where job_type in ('ingestion', 'feature_extraction', 'embedding', 'matching', 'llm_extraction');"
```

Meaning:

- `grant_client_matches`: deletes calculated matches.
- `match_runs`: deletes matching run records.
- `raw_grant_snapshots`: deletes raw HTML/API payload snapshots.
- `grants`: deletes normalized grant records.
- `discovered_grant_items`: видаляє Stage 1 item-level записи пошуку.
- `job_runs`: deletes pipeline job history for grant/matching reruns.

If you also need to reset imported clients/history:

```bash
docker compose exec db psql -U grant -d grant -c "delete from application_history;"
docker compose exec db psql -U grant -d grant -c "delete from client_profiles;"
docker compose exec db psql -U grant -d grant -c "delete from job_runs where job_type in ('import_clients', 'import_history');"
```

## Typical Full Local Retest Flow

This flow stays offline for AI parts by using `hash` embeddings and `rule` explanations:

```bash
docker compose up -d --build
docker compose exec app alembic upgrade head
docker compose exec app grant-tool seed-sources
docker compose exec app grant-tool import-manual-seed
docker compose exec app grant-tool ingest --all --limit 20 --mode incremental
docker compose exec app grant-tool extract-features --limit 100
docker compose exec app grant-tool embed --target all --provider hash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
docker compose exec app grant-tool explain-matches --limit 20 --provider rule
```

Then open:

```text
http://localhost:8000/
```

## Typical OpenAI Retest Flow

Use this only when `.env` has a valid `OPENAI_API_KEY`:

```bash
docker compose up -d --build
docker compose exec app grant-tool import-manual-seed
docker compose exec app grant-tool ingest --all --limit 20 --mode incremental
docker compose exec app grant-tool extract-features --limit 100 --use-llm
docker compose exec app grant-tool embed --target all --provider openai
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
docker compose exec app grant-tool explain-matches --limit 20 --provider openai
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
docker compose exec app python -m compileall grant_tool tests
```

Current test coverage includes repository, ingestion, manual import, extraction, matching, embeddings, explanations, and dashboard smoke tests.
