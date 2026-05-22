# Технології: AI Grant Matching Tool

## Мета документа

Цей документ фіксує технології, які використовуються в проєкті.

Тут не описується поетапна реалізація або майбутні операційні процеси. Для цього мають бути окремі planning або operations документи.

## Backend

- Мова: `Python`
- Web framework: `FastAPI`
- API підхід: REST API
- ASGI server: `Uvicorn`
- Конфігурація: environment variables + `.env`

`FastAPI` використовується для backend API, health checks, dashboard routes та інтеграції з внутрішніми сервісами.

## Dashboard

- Template engine: `Jinja2`
- UI interaction: `HTMX`
- Styling: plain CSS

Цей стек вибраний для внутрішнього dashboard без складного frontend build pipeline.

## Database

- Main database: `PostgreSQL`
- Vector extension: `pgvector`
- ORM: `SQLAlchemy 2`
- Migrations: `Alembic`

`PostgreSQL` зберігає джерела, raw snapshots, нормалізовані гранти, клієнтів, історію заявок, matches і reports.

`pgvector` використовується для embedding-полів і semantic similarity.

## Data Model Storage

Ключові таблиці:

- `sources`
- `raw_grant_snapshots`
- `grants`
- `client_profiles`
- `application_history`
- `job_runs`
- `match_runs`
- `grant_client_matches`
- `reports`

Сирі дані з сайтів або API зберігаються окремо від очищених записів грантів.

## Grant Fetching

- HTTP client: `httpx`
- HTML parsing: `BeautifulSoup`
- XML/RSS parsing: Python standard library `xml.etree.ElementTree`
- URL handling: Python standard library `urllib.parse`

Основний підхід:

- API, якщо джерело має стабільний API;
- RSS, якщо API немає, але є feed;
- sitemap або HTML list page, якщо немає API/RSS;
- HTML detail pages для повного тексту гранту.

## Source Connectors

Кожне джерело має окремий connector.

Поточні MVP-джерела:

- EU Funding & Tenders Portal
- Prostir
- Diia Business
- GURT

Connector відповідає тільки за отримання даних із конкретного джерела і перетворення їх у внутрішній формат `FetchedGrant`.

## Feature Extraction

- Deterministic extraction: Python rules, regex, keyword rules
- Optional LLM enrichment: OpenAI

Deterministic extraction використовується за замовчуванням.

LLM використовується тільки як додатковий механізм для неповних або нечітких полів, якщо налаштований `OPENAI_API_KEY`.

## AI And Embeddings

- AI provider: `OpenAI`
- LLM model: налаштовується через `LLM_MODEL`
- Embedding model: налаштовується через `EMBEDDING_MODEL`
- Embedding storage: `pgvector`

AI використовується для:

- optional field extraction;
- semantic embeddings;
- пояснення top matches.

AI не є єдиним джерелом правди. Основні факти мають походити з raw source data.

## Client Data

- Client profiles format: `CSV`
- Application history format: `CSV`

CSV вибрано як простий формат, який можна редагувати вручну або через spreadsheet tools.

## Matching

Matching використовує комбінацію:

- hard filters;
- keyword scoring;
- vector similarity;
- application history boost;
- score breakdown для пояснюваності.

Результати matching зберігаються у `match_runs` і `grant_client_matches`.

## Reports

- Primary report format: HTML inside dashboard
- Stored report content: database field in `reports`
- Optional text format: Markdown-compatible content

Reports будуються з уже збережених grants, clients, matches і explanations.

## Local Runtime

- Container runtime: Docker Compose
- Dependency management: `Poetry`
- Database container: PostgreSQL з `pgvector`
- App container: FastAPI application

Docker Compose використовується як основний локальний runtime для розробки й перевірки.

## Testing

- Test framework: Python `unittest`
- Test data: local fixtures
- Parser tests: fixture-based, без обов'язкового live internet

Fixture-based tests потрібні, щоб перевіряти connectors і extraction стабільно, навіть якщо зовнішній сайт тимчасово недоступний.

## Documentation

- Project documentation: Markdown
- API documentation: FastAPI OpenAPI docs
- Diagrams: SVG files in `docs`

Markdown використовується для planning, operations і пояснювальної документації.

## Operational Visibility

- Structured job status: `job_runs`
- Runtime logs: application/container logs
- Dashboard visibility: latest jobs, grants, matches, manual review markers

`job_runs` використовується для видимості запусків ingestion, import, extraction, embedding, matching і explanations.

Це тільки спосіб бачити результат уже запущених процесів.
