# Технологічний план: AI Grant Matching Tool

## Мета

Зафіксувати технології для MVP, щоб реалізація була послідовною і без повторного вибору стеку під час розробки.

## Core stack

- Backend: `FastAPI`
- Dashboard: `Jinja2` + `HTMX`
- API style: REST API first
- Frontend styling: plain CSS with minimal internal design system
- Dependency management: `Poetry`
- Python version: стабільна версія, бажано `Python 3.12`
- Local runtime: Docker Compose як основний спосіб запуску

Пояснення:

- `FastAPI` дає REST API, OpenAPI docs і просту інтеграцію з dashboard.
- `Jinja2 + HTMX` дозволяє зробити internal dashboard без складного frontend build step.
- REST API first залишає можливість пізніше додати React, зовнішній API або інтеграції.

## Local development workflow

- Основний перший запуск або запуск після Docker/dependency змін: `docker compose up --build`
- Звичайний щоденний запуск: `docker compose up`
- Повний запуск з worker і scheduler: `docker compose --profile worker --profile scheduler up --build`
- Зупинка services: `docker compose down`
- Перегляд logs: `docker compose logs -f`
- Перегляд статусу services: `docker compose ps`

Правило:

- Усі основні runtime dependencies мають запускатись через Docker Compose.
- `docker compose up` має самостійно підняти database, Redis, застосувати migrations, seed MVP sources і запустити app.
- Для цього використовується one-shot service `migrate`, який виконує `alembic upgrade head && grant-tool seed-sources`.
- `app`, `worker` і `beat` залежать від успішного завершення `migrate`.
- `docker compose down` не видаляє PostgreSQL data volume.
- `docker compose down -v` видаляє PostgreSQL data volume і використовується тільки для повного reset локальної бази.
- Локальний запуск через `poetry run uvicorn ...` дозволений тільки для точкового debugging.
- Якщо додається новий runtime service, його треба додати в `docker-compose.yml` і описати в документації.

## Database і migrations

- Main database: `PostgreSQL`
- Vector search: `pgvector`
- ORM: `SQLAlchemy 2`
- Migrations: `Alembic`
- Migration strategy: committed Alembic migration files

Пояснення:

- `PostgreSQL + pgvector` використовується і для structured data, і для embeddings.
- `SQLAlchemy 2 + Alembic` дає контрольовану schema evolution.
- Auto-create tables on startup не використовується як основний підхід.
- Migrations застосовує `migrate` service під час Docker Compose startup.
- Ручний fallback для migrations: `docker compose exec app alembic upgrade head`.

## Background jobs і automation

- Queue/jobs: `Celery`
- Broker: `Redis`
- Scheduled jobs: Celery beat або окремий scheduler поверх Celery

Jobs для MVP:

- seed sources
- ingestion кожні 6-12 годин
- reload client profiles
- reload application history
- run matching
- run LLM extraction для нових або incomplete grants
- generate embeddings або regenerate changed embeddings
- generate daily report

Job status зберігається в database через `JobRun`.

`JobRun` має покривати:

- `job_type`
- `source_id`, якщо job source-specific
- `status`: `pending`, `running`, `success`, `failed`, `partial`
- `started_at`
- `finished_at`
- `processed_count`
- `created_count`
- `updated_count`
- `skipped_count`
- `failed_count`
- `error_message`
- `job_metadata`

Пояснення:

- `Celery + Redis` складніші за простий scheduler, але краще підходять для довгих ingestion tasks, retries і job visibility.
- `JobRun` потрібен не тільки для Celery: ручні CLI-запуски ingestion/import/matching також мають створювати job history.

## Grant fetching і connectors

- Default fetching: `httpx`
- Default parsing: `BeautifulSoup`
- Browser automation: `Playwright` тільки якщо конкретне джерело неможливо стабільно обробити через `httpx`
- Crawler policy: conservative polite crawler
- Connector architecture: shared connector framework + source-specific implementations

Правила crawler-а:

- low request rate
- explicit user-agent
- timeouts
- limited retries
- no login bypass
- no paywall bypass
- no aggressive scraping

Connector framework:

- `BaseConnector`
- `FetchedGrant`
- `FetchedDetail`
- `NormalizedGrantDraft`
- `ConnectorResult`
- `ConnectorError`
- shared `HttpClient`
- shared content hashing
- shared ingestion service для raw snapshot save + normalized grant upsert

Мінімальний connector contract:

- `source_slug`
- `fetch_list`
- `parse_list`
- `fetch_detail`, якщо source потребує detail pages
- `parse_detail`, якщо source потребує detail pages
- `normalize_basic_fields`
- `run`

Порядок реалізації MVP connectors:

- EU Funding & Tenders Portal через API-style endpoint
- Prostir через RSS discovery + HTML detail parsing
- Diia Business через sitemap/list + HTML detail parsing
- GURT через HTML list/detail parsing

Статус Stage 3: done. Реалізовано `grant-tool ingest --source <source> --limit 20` і `grant-tool ingest --all --limit 20`.

Testing policy для connectors:

- parser tests працюють на local fixtures;
- fixtures зберігаються у `tests/fixtures/<source>/`;
- звичайний test run не залежить від live internet;
- live smoke checks можуть бути окремими manual/dev commands.

Пояснення:

- Спочатку для кожного джерела треба зробити technical discovery.
- Якщо сайт має API, RSS або structured endpoint, використовувати його.
- Якщо сторінки server-rendered, використовувати `httpx + BeautifulSoup`.
- Якщо сайт JS-heavy, додавати source-specific `Playwright` fallback.
- Framework потрібен, щоб post-MVP sources додавались як modules, а не як окремі one-off scripts.

## AI і embeddings

- AI provider: `OpenAI`
- LLM usage: extraction тільки для missing/unclear fields
- Explanations: LLM пояснює тільки top matches
- Embeddings: OpenAI embeddings
- Embedding storage: `pgvector`

Environment variables:

- `OPENAI_API_KEY`
- `LLM_MODEL`
- `EMBEDDING_MODEL`

Правила використання LLM:

- LLM не вирішує самостійно, чи є grant-client match.
- Hard filters, keyword score, vector similarity і application history boost формують shortlist.
- LLM отримує normalized grant card, client feature card, relevant application history records і score breakdown.
- LLM не має трактувати lost application як доказ поганого fit.
- LLM повертає explanation, risks і manual check notes.

Статус Stage 5: done for deterministic extraction foundation.

- `FeatureExtractionService` виконує rule-based extraction під час ingestion.
- `grant-tool extract-features` дозволяє повторно прогнати extraction для stored grants.
- Optional LLM extraction доступний через `--use-llm`, але за замовчуванням не запускається.
- LLM extraction має використовувати тільки raw source text/evidence, не вигадані поля.

## Client profiles

- Format: `CSV`
- CSV structure: simple CSV with semicolon-separated list fields

Приклад list fields:

- `technologies`
- `risks`
- `target_topics`
- `excluded_topics`

Пояснення:

- CSV легше редагувати вручну або в Google Sheets.
- Nested relational model для client profiles не потрібен у MVP.
- Google Drive інтеграція переноситься на post-MVP етап.

## Application history

- Format: окремий `CSV`
- Purpose: позитивний relevance signal для matching
- Outcome handling: результат попередньої подачі не зменшує fit score

Поля `application_history.csv`:

- `client_name`
- `grant_title`
- `grant_source`
- `program_name`
- `application_date`
- `result`
- `country`
- `applicant_type`
- `topics`
- `project_summary`
- `reusable_materials`
- `similarity_weight`
- `notes`

Allowed `result` values:

- `won`
- `lost`
- `rejected`
- `not_submitted`
- `unknown`

Правила використання application history:

- Якщо клієнт уже подавався на схожі гранти, score нового схожого гранта збільшується.
- Win/loss result не є негативним fit-сигналом.
- Lost application означає, що грант міг бути релевантним, але заявка не виграла.
- Rejected або not_submitted можуть створити manual review note, але не score penalty.
- `similarity_weight` дозволяє вручну підсилити або послабити конкретний історичний запис.
- `reusable_materials` збільшує score, якщо попередні матеріали можна використати повторно.

## Data storage policy

- Raw data policy: store every raw snapshot version
- Deduplication: source URL, source-specific ID, checksum
- Normalized grants оновлюються після кожного нового snapshot

Пояснення:

- Зберігання кожної raw snapshot version дає audit trail.
- Можна бачити, як змінювався grant з часом.
- Це корисно для deadline/status updates і розбору помилок extraction.

## Dashboard і manual review

- Dashboard type: internal web dashboard
- Auth for MVP: no auth, local-only
- Manual review workflow: status labels only

Manual review statuses:

- `new`
- `reviewed`
- `relevant`
- `irrelevant`
- `duplicate`
- `needs_check`

Dashboard pages:

- grants
- client profiles
- matches
- reports
- job status

Пояснення:

- Без auth MVP простіше запускати локально.
- Якщо dashboard буде відкриватись поза локальним середовищем, auth треба додати до deployment.

## Reports

- Primary report: HTML report inside dashboard
- Export: downloadable Markdown

Report має включати:

- нові гранти
- оновлені гранти
- top matches по клієнтах
- пояснення релевантності
- ризики
- manual check items

Пояснення:

- HTML report зручний для перегляду в dashboard.
- Markdown export зручно переносити в Notion, Google Docs, GitHub або email draft.

## API documentation

- FastAPI auto OpenAPI docs
- Markdown API docs у репозиторії

Пояснення:

- OpenAPI достатній для інтерактивного перегляду endpoints.
- Markdown docs потрібні, бо проєкт обрано як REST API first.

## Operational visibility

- Structured logs
- Job status in database

Job status має показувати:

- job type
- source, якщо job source-specific
- status
- started_at
- finished_at
- processed_count
- created_count
- updated_count
- skipped_count
- failed_count
- error message
- source-specific metadata або parser warnings

Пояснення:

- Logs only недостатньо для scheduled ingestion.
- Job status у database дозволить показувати стан crawler-а прямо в dashboard.
- Partial failures мають бути видимі: якщо один detail page впав, job може бути `partial`, а не повністю `failed`.

## Відкладено після MVP

- Google Drive connector
- Google OAuth або інша auth
- React frontend
- PDF export
- Email digest
- Slack notifications
- Full task workflow з owner, due date, comments і history
- Provider-agnostic AI abstraction
- Local LLM/embedding models
