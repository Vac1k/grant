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

- Основний запуск: `docker compose up --build`
- Повний запуск з worker і scheduler: `docker compose --profile worker --profile scheduler up --build`
- Зупинка services: `docker compose down`
- Перегляд logs: `docker compose logs -f`
- Перегляд статусу services: `docker compose ps`

Правило:

- Усі основні runtime dependencies мають запускатись через Docker Compose.
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

## Background jobs і automation

- Queue/jobs: `Celery`
- Broker: `Redis`
- Scheduled jobs: Celery beat або окремий scheduler поверх Celery

Jobs для MVP:

- ingestion кожні 6-12 годин
- reload client profiles
- reload application history
- run matching
- generate daily report

Пояснення:

- `Celery + Redis` складніші за простий scheduler, але краще підходять для довгих ingestion tasks, retries і job visibility.

## Grant fetching і connectors

- Default fetching: `httpx`
- Default parsing: `BeautifulSoup`
- Browser automation: `Playwright` тільки якщо конкретне джерело неможливо стабільно обробити через `httpx`
- Crawler policy: conservative polite crawler

Правила crawler-а:

- low request rate
- explicit user-agent
- timeouts
- limited retries
- no login bypass
- no paywall bypass
- no aggressive scraping

Пояснення:

- Спочатку для кожного джерела треба зробити technical discovery.
- Якщо сайт має API, RSS або structured endpoint, використовувати його.
- Якщо сторінки server-rendered, використовувати `httpx + BeautifulSoup`.
- Якщо сайт JS-heavy, додавати source-specific `Playwright` fallback.

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
- error message
- number of processed records

Пояснення:

- Logs only недостатньо для scheduled ingestion.
- Job status у database дозволить показувати стан crawler-а прямо в dashboard.

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
