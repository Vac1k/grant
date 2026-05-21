# Start Guide

Цей документ описує базовий локальний запуск AI Grant Matching Tool.

## Що зараз реалізовано

Проєкт уже містить повний локальний MVP flow:

- FastAPI app з health API і dashboard.
- PostgreSQL 16 з `pgvector`.
- Redis.
- one-shot `migrate` service, який запускає Alembic migrations і seed MVP sources.
- Ingestion для `eu-funding`, `prostir`, `diia-business`, `gurt`.
- deterministic Stage 5 feature extraction з optional OpenAI LLM enrichment.
- manual CSV import для client profiles і application history.
- Stage 6 shortlist matching.
- Stage 7 embeddings через local hash provider або OpenAI.
- Stage 8 match explanations через local rule provider або OpenAI.
- Stage 9 dashboard pages.
- Celery worker/beat services підготовлені через Docker Compose profiles.

## Основний спосіб запуску

Основний спосіб запуску проєкту - Docker Compose.

Це важливо, бо app залежить не тільки від Python/FastAPI, а й від:

- PostgreSQL з `pgvector`
- Redis
- Alembic migrations
- CLI jobs, які працюють з тією самою database

## Перший запуск

Перейти в директорію проєкту:

```bash
cd /Users/vac1k/Projects/ai_replace_grandwriters/grant
```

Створити локальний `.env` файл, якщо його ще немає:

```bash
cp .env.example .env
```

Для повністю локального smoke flow `OPENAI_API_KEY` можна залишити порожнім. OpenAI потрібен тільки для:

- `grant-tool extract-features --use-llm`
- `grant-tool embed --provider openai`
- `grant-tool explain-matches --provider openai`

Запустити local stack:

```bash
docker compose up --build
```

Під час запуску Docker Compose автоматично запускає service `migrate`.
Він виконує:

```bash
alembic upgrade head
grant-tool seed-sources
```

Тобто на чистій базі не треба окремо запускати migrations або seed MVP sources.

Після першого build щоденний запуск можна робити коротшою командою:

```bash
docker compose up
```

## URLs

Після запуску app доступний тут:

- dashboard overview: `http://localhost:8000/`
- grants: `http://localhost:8000/grants`
- clients: `http://localhost:8000/clients`
- matches: `http://localhost:8000/matches`
- report view: `http://localhost:8000/report`
- health: `http://localhost:8000/api/v1/health`
- OpenAPI docs: `http://localhost:8000/docs`

Health check:

```bash
curl http://localhost:8000/api/v1/health
```

Очікувана відповідь:

```json
{"status":"ok","service":"AI Grant Matching Tool","environment":"local"}
```

## Звичайний щоденний запуск

Якщо `.env` вже створений:

```bash
docker compose up
```

Якщо змінювались dependencies, Dockerfile або Docker image треба перебудувати:

```bash
docker compose up --build
```

Для background mode:

```bash
docker compose up -d --build
```

## Базовий MVP smoke flow

Після старту app можна завантажити seed clients/history, зібрати grants, порахувати matches і подивитись dashboard:

```bash
docker compose exec app grant-tool import-manual-seed
docker compose exec app grant-tool ingest --all --limit 20
docker compose exec app grant-tool extract-features --limit 100
docker compose exec app grant-tool embed --target all --provider hash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
docker compose exec app grant-tool explain-matches --limit 20 --provider rule
```

Після цього відкрити:

```text
http://localhost:8000/
```

`hash` embeddings і `rule` explanations призначені для локального/offline smoke testing. Для реальної semantic якості використовувати OpenAI provider-и.

## Manual seed data

Manual seed files лежать тут:

- `data/manual_seed/client_profiles.manual.csv`
- `data/manual_seed/application_history.manual.csv`
- `data/manual_seed/document_inventory.manual.csv`

Імпорт client profiles і application history разом:

```bash
docker compose exec app grant-tool import-manual-seed
```

Окремо:

```bash
docker compose exec app grant-tool import-clients --file data/manual_seed/client_profiles.manual.csv
docker compose exec app grant-tool import-application-history --file data/manual_seed/application_history.manual.csv
```

`document_inventory.manual.csv` зараз є ручним інвентарем документів і не імпортується CLI командою.

## Ingestion

Запустити одне джерело:

```bash
docker compose exec app grant-tool ingest --source eu-funding --limit 20
docker compose exec app grant-tool ingest --source prostir --limit 20
docker compose exec app grant-tool ingest --source diia-business --limit 20
docker compose exec app grant-tool ingest --source gurt --limit 20
```

Запустити всі MVP sources:

```bash
docker compose exec app grant-tool ingest --all --limit 20
```

`--limit` означає максимальну кількість grants на source. Default value: `20`.

Ingestion зберігає `RawGrantSnapshot`, робить normalized `Grant` upsert і запускає deterministic Stage 5 enrichment перед збереженням grant.

Кожен ingestion запуск створює `JobRun`:

```bash
docker compose exec app grant-tool jobs list --type ingestion
```

## Feature Extraction

Stage 5 extraction нормалізує grant feature card:

- `status`
- `deadline_at` / `deadline_text`
- `funding_amount_*` / `currency`
- `opportunity_type` / `support_type`
- `applicant_types`
- `topics`
- `countries`
- `eligibility_text`
- `restrictions_text`
- `cofinancing_text`
- `consortium_text`
- `extraction_confidence`
- `extraction_metadata.feature_card`
- `needs_manual_review`

Повторно запустити extraction для вже збережених grants:

```bash
docker compose exec app grant-tool extract-features --limit 100
```

Для конкретного source:

```bash
docker compose exec app grant-tool extract-features --source prostir --limit 20
```

Optional LLM extraction:

```bash
docker compose exec app grant-tool extract-features --limit 100 --use-llm
```

`--use-llm` працює тільки якщо заданий `OPENAI_API_KEY`.

## Matching, Embeddings And Explanations

Run strict Stage 6 matching:

```bash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20
```

Generate local deterministic embeddings:

```bash
docker compose exec app grant-tool embed --target all --provider hash
```

Run matching with vector similarity:

```bash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
```

Generate local deterministic explanations:

```bash
docker compose exec app grant-tool explain-matches --limit 20 --provider rule
```

OpenAI variants:

```bash
docker compose exec app grant-tool embed --target all --provider openai
docker compose exec app grant-tool explain-matches --limit 20 --provider openai
```

OpenAI embedding/explanation commands require `OPENAI_API_KEY` in `.env`.

## Worker And Scheduler

Worker і scheduler підготовлені через Docker Compose profiles, але основний MVP flow зараз запускається через CLI commands.

Запуск з worker і scheduler:

```bash
docker compose --profile worker --profile scheduler up --build
```

Ця команда запускає:

- `migrate`
- `app`
- `db`
- `redis`
- `worker`
- `beat`

## Logs And Status

Дивитись logs усіх services:

```bash
docker compose logs -f
```

Дивитись logs тільки app:

```bash
docker compose logs -f app
```

Дивитись статус services:

```bash
docker compose ps
```

## Database Migrations

Звичайно migrations запускати вручну не треба: service `migrate` робить це під час `docker compose up`.

Якщо треба вручну повторно застосувати migrations:

```bash
docker compose exec app alembic upgrade head
```

Подивитись поточну Alembic revision:

```bash
docker compose exec app alembic current
```

Подивитись таблиці в PostgreSQL:

```bash
docker compose exec db psql -U grant -d grant -c "\dt"
```

## Зупинка

Зупинити services:

```bash
docker compose down
```

`docker compose down` зупиняє і видаляє containers/network, але не видаляє PostgreSQL data volume.

Зупинити services і видалити volumes з database data:

```bash
docker compose down -v
```

Команду `docker compose down -v` використовувати обережно, бо вона видаляє локальні дані PostgreSQL.

## Локальний запуск без Docker

Цей спосіб не є основним. Він потребує локальних PostgreSQL/Redis з URL з `.env`.

```bash
poetry install
poetry run alembic upgrade head
poetry run grant-tool seed-sources
poetry run uvicorn grant_tool.main:app --reload
```
