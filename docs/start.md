# Start Commands

Команди запускати з кореня проєкту.

## Перейти в проєкт

```bash
cd C:\Users\volodymyr.onyshchenk\PycharmProjects\grant
```

## Підготувати `.env`

```bash
cp .env.example .env
```

Для PowerShell:

```powershell
Copy-Item .env.example .env
```

## Запуск через Docker Compose

Перший запуск або запуск після змін у Docker/dependencies:

```bash
docker compose up --build
```

Звичайний запуск:

```bash
docker compose up
```

Запуск у background mode:

```bash
docker compose up -d --build
```

Запуск без rebuild:

```bash
docker compose up -d
```

## URL-и

```text
http://localhost:8000/
http://localhost:8000/grants
http://localhost:8000/clients
http://localhost:8000/matches
http://localhost:8000/report
http://localhost:8000/api/v1/health
http://localhost:8000/docs
```

Health check:

```bash
curl http://localhost:8000/api/v1/health
```

## Базовий локальний smoke flow

```bash
docker compose exec app grant-tool import-manual-seed
docker compose exec app grant-tool ingest --all --limit 20 --mode incremental
docker compose exec app grant-tool extract-features --limit 100
docker compose exec app grant-tool embed --target all --provider hash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
docker compose exec app grant-tool explain-matches --limit 20 --provider rule
```

## Імпорт ручних даних

```bash
docker compose exec app grant-tool import-manual-seed
```

```bash
docker compose exec app grant-tool import-clients --file data/manual_seed/client_profiles.manual.csv
docker compose exec app grant-tool import-application-history --file data/manual_seed/application_history.manual.csv
```

## Ingestion

Усі джерела:

```bash
docker compose exec app grant-tool ingest --all --limit 20 --mode incremental
```

Окремі джерела:

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
docker compose exec app grant-tool ingest --source grantforward --limit 10 --mode incremental
```

`incremental` перечитує listing/RSS/API/search endpoint, але пропускає detail-завантаження для вже відомих item-level грантів. Для повторного detail-завантаження відомих item можна запустити `--mode backfill`.

Для `grantforward` використовуй `--limit 10`: публічний search endpoint дає тільки першу сторінку без login, а більший limit повертає login/sign-up message.

Для `gurt` connector існує, але live production access зараз може падати через Cloudflare/human-check. Це documented limitation, не причина обходити захист.

Перевірити ingestion jobs:

```bash
docker compose exec app grant-tool jobs list --type ingestion
```

Перевірити знайдені Stage 1 item:

```bash
docker compose exec db psql -U grant -d grant -c "select source_slug, discovery_status, detail_fetch_status, count(*) from discovered_grant_items group by source_slug, discovery_status, detail_fetch_status order by source_slug;"
```

Перевірити operational search report:

```bash
docker compose exec app grant-tool search-report
```

Перевірити Step 9 quality gate:

```bash
docker compose exec app grant-tool quality-gate
```

Quality gate проходить тільки тоді, коли кожне implementable джерело, крім `gurt`, має мінімум 10 quality-approved grants у `grants`.

## Feature Extraction

```bash
docker compose exec app grant-tool extract-features --limit 100
```

```bash
docker compose exec app grant-tool extract-features --source prostir --limit 20
```

З OpenAI:

```bash
docker compose exec app grant-tool extract-features --limit 100 --use-llm
```

## Embeddings

Локальний deterministic provider:

```bash
docker compose exec app grant-tool embed --target all --provider hash
```

OpenAI provider:

```bash
docker compose exec app grant-tool embed --target all --provider openai
```

## Matching

```bash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20
```

```bash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
```

## Explanations

Локальний rule provider:

```bash
docker compose exec app grant-tool explain-matches --limit 20 --provider rule
```

OpenAI provider:

```bash
docker compose exec app grant-tool explain-matches --limit 20 --provider openai
```

## Jobs

```bash
docker compose exec app grant-tool jobs list
```

```bash
docker compose exec app grant-tool jobs list --type ingestion
docker compose exec app grant-tool jobs list --type feature_extraction
docker compose exec app grant-tool jobs list --type embedding
docker compose exec app grant-tool jobs list --type matching
docker compose exec app grant-tool jobs list --type llm_extraction
```

```bash
docker compose exec app grant-tool jobs show <job-id>
```

## Database And Migrations

```bash
docker compose exec app alembic upgrade head
```

```bash
docker compose exec app alembic current
```

```bash
docker compose exec db psql -U grant -d grant -c "\dt"
```

```bash
docker compose exec db psql -U grant -d grant
```

## Логи і статус

```bash
docker compose logs -f
```

```bash
docker compose logs -f app
```

```bash
docker compose ps
```

## Зупинка

Зупинити containers без видалення даних PostgreSQL:

```bash
docker compose down
```

Зупинити containers і видалити volumes:

```bash
docker compose down -v
```

## Локальний запуск без Docker

```bash
poetry install
poetry run alembic upgrade head
poetry run grant-tool seed-sources
poetry run uvicorn grant_tool.main:app --reload
```
