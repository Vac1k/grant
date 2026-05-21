# Поетапний план реалізації: AI Grant Matching Tool

## Мета

Розбити MVP на практичні етапи реалізації, щоб рухатись від простої робочої системи до повного інструмента для збору грантів, matching з клієнтами та генерації звітів.

MVP фокус:

- EU Funding & Tenders Portal
- Prostir grants
- GURT grants
- Diia Business finance programs
- ручні client profiles через `CSV`
- application history через окремий `CSV`
- web dashboard
- LLM для extraction і пояснення top matches

## Stage 1: База проєкту і локальний запуск

Status: done

Ціль: підготувати технічну основу, на якій можна будувати ingestion, matching і dashboard.

Що зробити:

- Привести Python-проєкт до нормальної структури package.
- Змінити Python target на стабільну версію, бажано `^3.12`.
- Додати базові dependencies:
  - `FastAPI`
  - `Uvicorn`
  - `SQLAlchemy`
  - `Alembic`
  - `psycopg`
  - `Jinja2`
  - `httpx`
  - `beautifulsoup4`
  - `pydantic`
  - `python-dotenv`
  - `PyYAML`
- Додати `docker-compose.yml` для:
  - web app
  - PostgreSQL
  - worker/scheduler у наступних етапах
- Зробити Docker Compose основним способом запуску локального MVP:
  - `docker compose up --build`
- Документувати прямі Docker Compose команди:
  - `docker compose up --build`
  - `docker compose --profile worker --profile scheduler up --build`
  - `docker compose down`
  - `docker compose logs -f`
  - `docker compose ps`
- Додати `.env.example` з ключовими налаштуваннями:
  - `DATABASE_URL`
  - `OPENAI_API_KEY`
  - `LLM_MODEL`
  - `EMBEDDING_MODEL`
  - `APP_ENV`
- Створити мінімальний FastAPI app з health route.

Результат етапу:

- Проєкт запускається локально.
- Основний запуск виконується однією Docker Compose командою.
- Є база даних.
- Є мінімальний web app.
- Є підготовлена конфігурація для наступних етапів.

Фактично зроблено:

- Створено package структуру `grant_tool`.
- Додано `FastAPI` app.
- Додано root endpoint `/`.
- Додано health endpoint `/api/v1/health`.
- Оновлено `pyproject.toml` і `poetry.lock`.
- Додано `Dockerfile`.
- Додано `docker-compose.yml`.
- Додано PostgreSQL з `pgvector`.
- Додано Redis.
- Додано one-shot Docker Compose service `migrate`, який запускає migrations і source seed перед app.
- Додано Celery worker/beat placeholders через Docker Compose profiles.
- Додано `.env.example`.
- Налаштовано реальний локальний `.env`.
- Додано `.dockerignore`, щоб `.env` не копіювався в image і не монтувався в app container.
- Додано `docs/start.md` з Docker Compose командами.

Перевірено:

- `docker compose up --build -d`
- `docker compose ps`
- `curl http://localhost:8000/api/v1/health`
- `curl -I http://localhost:8000/docs`
- `docker compose down`

## Stage 2: Data model і database layer

Status: done

Ціль: створити структуру даних, у яку можна зберігати raw grants, normalized grants, clients, matches і reports.

Перед реалізацією Stage 2 врахувати аналіз полів з `planning/fields.md`.
Перед реалізацією Stage 2 також врахувати аналіз доступу до джерел з `planning/source_access.md`.

Що зробити:

- Додати SQLAlchemy models для:
  - `Source`
  - `RawGrant` або `RawGrantSnapshot`
  - `Grant`
  - `ClientProfile`
  - `ApplicationHistory`
  - `MatchRun`
  - `GrantClientMatch`
  - `Report`
- У `Source` зберігати strategy доступу до джерела:
  - `api`
  - `wp_rest`
  - `rss`
  - `sitemap_html`
  - `html`
  - `browser`
  - `manual`
- У `Grant` не робити business fields required, окрім технічних полів, `source_url`, `title`, `status`.
- Додати JSON fields для source-specific metadata, documents і extraction metadata.
- Зберігати raw snapshots окремо від normalized grants.
- Додати Alembic migrations.
- Реалізувати database session management.
- Додати repository/service layer для основних операцій:
  - створити або оновити source
  - зберегти raw grant
  - upsert normalized grant
  - завантажити client profiles
  - зберегти match results
  - зберегти daily report

Результат етапу:

- Дані мають стабільну схему.
- Повторний запуск ingestion може оновлювати існуючі записи.
- Є основа для deduplication через URL, source ID і checksum.

Фактично зроблено:

- Додано SQLAlchemy database layer у `grant_tool/db`.
- Додано models:
  - `Source`
  - `RawGrantSnapshot`
  - `Grant`
  - `ClientProfile`
  - `ApplicationHistory`
  - `MatchRun`
  - `GrantClientMatch`
  - `Report`
- Додано `access_strategy` для `Source`.
- Додано JSON fields для raw payload, source metadata, extraction metadata, documents, client topics, match evidence і report metadata.
- Додано окреме збереження raw snapshots.
- Додано Alembic config і першу migration.
- Додано database session management.
- Додано repository layer для основних операцій:
  - source upsert;
  - raw snapshot save;
  - grant upsert;
  - client profile upsert;
  - application history save;
  - match run create;
  - match result save/upsert;
  - report save.
- Оновлено Docker Compose volumes для `migrations` і `alembic.ini`.
- Оновлено `docs/start.md` з database migration командами.
- Startup flow оновлено: migrations і source seed тепер виконує Docker Compose service `migrate` автоматично під час `docker compose up`.

Перевірено:

- `poetry run python -m compileall grant_tool migrations`
- `docker compose up --build -d`
- `docker compose exec app alembic upgrade head`
- `docker compose exec db psql -U grant -d grant -c "\dt"`
- `curl http://localhost:8000/api/v1/health`
- CRUD smoke check repository layer з rollback.

## Stage 2.5: Job tracking і source seeding

Status: done

Ціль: додати операційний контроль перед реальним ingestion, щоб кожен запуск збору, імпорту, matching або report generation мав статус, лічильники і помилки.

Чому це потрібно:

- Ingestion буде працювати з нестабільними зовнішніми сайтами.
- Один source може впасти, але вся система не має ламатись.
- Потрібно бачити, коли джерело востаннє успішно оновлювалось.
- Повторний запуск має бути безпечним і зрозумілим.
- Dashboard має показувати не тільки grants, а й стан pipeline.

Що зробити:

- Додати SQLAlchemy model `JobRun`.
- Додати Alembic migration для `job_runs`.
- Поля `JobRun`:
  - `id`
  - `job_type`: `ingestion`, `import_clients`, `import_history`, `matching`, `llm_extraction`, `embedding`, `report`, `seed_sources`
  - `source_id`, якщо job прив'язаний до конкретного source
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
- Додати repository/service methods:
  - `start_job`
  - `finish_job_success`
  - `finish_job_failed`
  - `mark_job_partial`
  - `increment_job_counters`
- Додати seed для MVP sources:
  - EU Funding & Tenders Portal
  - Prostir grants
  - GURT grants
  - Diia Business finance programs
- Додати CLI commands:
  - `grant-tool seed-sources`
  - `grant-tool jobs list`
  - `grant-tool jobs show <job_id>`
- Додати базові тести:
  - створення job;
  - success/failure завершення;
  - idempotent source seed;
  - counters update.

Результат етапу:

- Перед Stage 3 у системі вже є записи source-ів.
- Кожен ingestion запуск має audit trail.
- Помилки connector-ів можна бачити в database/dashboard.
- Stage 10 automation пізніше буде використовувати той самий `JobRun`, а не окремий механізм.

Фактично зроблено:

- Додано SQLAlchemy model `JobRun`.
- Додано enum-и `JobType` і `JobStatus`.
- Додано Alembic migration `20260519_0002_create_job_runs.py`.
- Додано relationship `Source.job_runs`.
- Додано repository methods:
  - `start_job`;
  - `get_job`;
  - `list_jobs`;
  - `increment_job_counters`;
  - `finish_job_success`;
  - `finish_job_failed`;
  - `mark_job_partial`;
  - `get_source_by_slug`;
  - `list_sources`.
- Додано MVP source seed definitions для:
  - EU Funding & Tenders Portal;
  - Prostir grants;
  - Diia Business finance programs;
  - GURT grants.
- Додано `seed_mvp_sources`.
- Додано CLI commands:
  - `grant-tool seed-sources`;
  - `grant-tool jobs list`;
  - `grant-tool jobs show <job_id>`.
- Оновлено Dockerfile, щоб console script `grant-tool` був доступний у контейнері.
- Оновлено Docker Compose:
  - додано одноразовий service `migrate`;
  - `migrate` виконує `alembic upgrade head && grant-tool seed-sources`;
  - `app`, `worker` і `beat` стартують після успішного `migrate`.
- Додано unit tests для Stage 2 repository smoke flow, job lifecycle, failure/partial statuses і idempotent source seed.

Перевірено:

- `poetry run python -m compileall grant_tool migrations tests`
- `poetry run python -m unittest`
- `poetry run grant-tool --help`
- `docker compose up -d --build app`
- `docker compose down`
- `docker compose up -d --build`
- `docker compose ps -a`
- `docker compose logs migrate`
- `docker compose exec app grant-tool --help`
- `docker compose exec app alembic upgrade head`
- `docker compose exec app alembic current`
- `docker compose exec app grant-tool seed-sources`
- повторний `seed-sources` створює updates, а не дублікати
- `docker compose exec app grant-tool jobs list --limit 5`
- `docker compose exec app grant-tool jobs show <job_id>`
- `docker compose exec app python -m unittest`
- `curl -s http://localhost:8000/api/v1/health`
- `docker compose exec db psql -U grant -d grant -c "\dt"`
- `docker compose exec db psql -U grant -d grant -c "select slug, access_strategy, enabled from sources order by slug;"`
- `docker compose exec db psql -U grant -d grant -c "select count(*) from sources;"`

## Stage 3: Ingestion connector framework і MVP connectors

Status: done

Ціль: навчити систему збирати гранти з перших 4 джерел.

Перед реалізацією Stage 3 врахувати source strategy з `planning/source_access.md`.

Stage 3 не треба реалізовувати як чотири окремі хаотичні scripts. Спочатку потрібно зробити спільний connector framework, а потім підключати джерела по одному.

### Stage 3.0: Connector framework

Ціль: створити однаковий контракт для всіх джерел.

Що зробити:

- Створити загальний interface для connector-ів:
  - `source_slug`
  - `fetch_list`
  - `fetch_detail`, якщо потрібно
  - `parse_list`
  - `parse_detail`
  - `normalize_basic_fields`
  - `run`
- Додати shared data objects:
  - `FetchedGrant`
  - `FetchedDetail`
  - `NormalizedGrantDraft`
  - `ConnectorResult`
  - `ConnectorError`
- Додати shared HTTP client:
  - `httpx`
  - configured user-agent з `HTTP_USER_AGENT`
  - timeout
  - limited retries
  - per-source rate limit
  - content-type збереження
  - HTTP status збереження
- Додати content hashing:
  - hash raw JSON для API sources;
  - hash raw HTML/text для HTML sources;
  - hash має використовуватись для `RawGrantSnapshot.content_hash`.
- Додати ingestion service:
  - завантажити `Source` з database;
  - запустити connector;
  - зберегти raw snapshot до normalization;
  - upsert normalized grant;
  - оновити `JobRun` counters;
  - не падати всім job через одну помилку detail page.
- Додати CLI commands:
  - `grant-tool ingest --source eu-funding`
  - `grant-tool ingest --source prostir`
  - `grant-tool ingest --source diia-business`
  - `grant-tool ingest --source gurt`
  - `grant-tool ingest --all`
- Додати fixture-based tests:
  - parser tests мають працювати без internet;
  - fixtures зберігати у `tests/fixtures/<source>/`;
  - live network tests не мають бути обов'язковими для звичайного test run.

Результат Stage 3.0:

- Є один ingestion pattern для всіх джерел.
- Новий source можна додати без зміни core ingestion service.
- Реальні connectors мають однакові counters, error handling і raw snapshot behavior.

### Stage 3.1: EU Funding & Tenders Portal connector

Ціль: першим реалізувати найбільш структуроване джерело.

Що зробити:

- Реалізувати connector для EU Funding & Tenders Portal:
  - використовувати API-style endpoint;
  - не скрейпити HTML як основний шлях;
  - зберігати source JSON у raw snapshots.
  - нормалізувати:
    - source record id / topic id
    - title
    - status
    - call/program
    - description/summary
    - opening date
    - deadline dates
    - keywords/topics, якщо доступні
    - budget/funding text, якщо доступний
    - source URL
- Додати fixture JSON response і parser tests.

Результат Stage 3.1:

- Database schema перевірена на структурованому API source.
- Можна запускати перший реальний ingestion job.

### Stage 3.2: Prostir connector

Ціль: реалізувати українське джерело з RSS discovery і HTML detail extraction.

Що зробити:

- Реалізувати connector для Prostir:
  - RSS для discovery;
  - HTML detail parsing для повного тексту.
  - з RSS брати:
    - title
    - source URL
    - publication date
    - summary/excerpt
  - з detail HTML брати:
    - full text
    - deadline text/date, якщо можна визначити deterministic parsing
    - documents/links
    - contact/application instructions, якщо доступні
- Додати fixture RSS і detail HTML.
- Додати parser tests для RSS і detail HTML.

Результат Stage 3.2:

- MVP має перше українське джерело.
- Raw HTML/text зберігається для Stage 5 LLM extraction.

### Stage 3.3: Diia Business finance programs connector

Ціль: додати джерело business support programs, яке не завжди є класичним grant source.

Що зробити:

- Реалізувати connector для Diia Business finance programs:
  - sitemap/list pages для discovery;
  - HTML detail parsing для програм фінансування.
  - розрізняти `opportunity_type` і `support_type`;
  - зберігати finance programme metadata у `source_metadata`.
- Нормалізувати, якщо доступно:
  - title
  - provider/institution
  - support type
  - amount/funding text
  - target audience
  - conditions
  - external application URL
- Додати fixture sitemap/list HTML і detail HTML.
- Додати parser tests.

Результат Stage 3.3:

- Система покриває не тільки grants, а й finance/support programmes для українських компаній.

### Stage 3.4: GURT connector

Ціль: додати менш структуроване українське джерело після стабілізації framework на простіших sources.

Що зробити:

- Реалізувати connector для GURT:
  - HTML list/detail parsing;
  - ізолювати parsing logic, бо джерело менш структуроване.
  - робити conservative requests;
  - зберігати full raw text для подальшої LLM extraction;
  - не вимагати deadline/amount/funder як required fields.
- Додати fixture list HTML і detail HTML.
- Додати parser tests.

Результат Stage 3.4:

- Система має всі 4 MVP sources.
- Неструктуровані джерела не ламають normalized schema.

### Загальні правила Stage 3

- Додати polite fetch behavior:
  - user-agent
  - timeout
  - retry з обмеженням
  - не робити агресивний scraping
- Кожен connector має:
  - зберігати raw data перед normalized upsert;
  - повертати stable source URL;
  - повертати source-specific ID, якщо є;
  - рахувати processed/created/updated/skipped/failed;
  - не створювати дублікати при повторному запуску;
  - логувати source-specific parser warnings.
- Якщо detail page не завантажилась:
  - list item все одно можна зберегти як partial grant;
  - job може завершитись `partial`, а не `failed`;
  - error має бути в `JobRun.job_metadata` або logs.

Результат етапу:

- Система може зібрати список грантів із MVP-джерел.
- Raw data зберігається перед нормалізацією.
- Нові й оновлені гранти можна відрізняти через checksum.
- Database schema Stage 2 перевіряється на реальних source payloads.
- Кожен ingestion запуск видно через `JobRun`.
- Connector framework готовий для post-MVP sources.

Фактично зроблено:

- Додано package `grant_tool/ingestion`.
- Додано shared Stage 3 framework:
  - `BaseConnector`;
  - `HttpClient`;
  - `HttpResponse`;
  - `content_hash`;
  - `NormalizedGrantDraft`;
  - `FetchedGrant`;
  - `ConnectorResult`;
  - `ConnectorError`;
  - `IngestionService`;
  - `IngestionSummary`.
- Додано helpers для:
  - stable JSON hashing;
  - text cleanup;
  - HTML text extraction;
  - RSS/XML/sitemap parsing;
  - deadline extraction;
  - document link extraction;
  - funding text extraction;
  - absolute URL normalization.
- Додано `GrantRepository.get_grant_by_source_identity`.
- Додано source-specific connectors:
  - `EUFundingConnector`;
  - `ProstirConnector`;
  - `DiiaBusinessConnector`;
  - `GurtConnector`.
- Додано connector registry `CONNECTOR_CLASSES`.
- Додано CLI command:
  - `grant-tool ingest --source <source> --limit 20`;
  - `grant-tool ingest --all --limit 20`.
- Default ingestion limit: `20` grants per source.
- `grant-tool ingest` перед запуском виконує idempotent `seed_mvp_sources`.
- `IngestionService`:
  - створює `JobRun` типу `ingestion`;
  - запускає connector;
  - зберігає `RawGrantSnapshot`;
  - робить normalized `Grant` upsert;
  - оновлює counters `processed/created/updated/failed`;
  - позначає job як `success`, `partial` або `failed`.
- Реалізовано partial behavior:
  - помилка окремого detail page не має ламати весь source ingestion;
  - errors потрапляють у `JobRun.job_metadata`.
- Prostir connector має fallback:
  - спершу RSS;
  - якщо RSS порожній, HTML listing з `?grants=` links.
- Додано fixtures:
  - `tests/fixtures/eu_funding/search_response.json`;
  - `tests/fixtures/prostir/feed.xml`;
  - `tests/fixtures/prostir/detail.html`;
  - `tests/fixtures/diia_business/sitemap.xml`;
  - `tests/fixtures/diia_business/detail.html`;
  - `tests/fixtures/gurt/list.html`;
  - `tests/fixtures/gurt/detail.html`.
- Додано tests:
  - EU API parser;
  - Prostir RSS + detail parser;
  - Diia sitemap + detail parser;
  - GURT list + detail parser;
  - ingestion service save/upsert/job integration.

Перевірено:

- `poetry run python -m compileall grant_tool tests`
- `poetry run python -m unittest`
- `poetry run grant-tool --help`
- `poetry run grant-tool ingest --help`
- `docker compose up -d --build`
- `docker compose exec app python -m unittest`
- `docker compose exec app grant-tool ingest --help`
- `curl -s http://localhost:8000/api/v1/health`
- Live smoke checks з conservative `--limit 2`:
  - `docker compose exec app grant-tool ingest --source eu-funding --limit 2`
  - `docker compose exec app grant-tool ingest --source prostir --limit 2`
  - `docker compose exec app grant-tool ingest --source diia-business --limit 2`
  - `docker compose exec app grant-tool ingest --source gurt --limit 2`
- Multi-source smoke:
  - `docker compose exec app grant-tool ingest --all --limit 1`
- DB verification:
  - `docker compose exec db psql -U grant -d grant -c "select s.slug, count(g.id) as grants from sources s left join grants g on g.source_id=s.id group by s.slug order by s.slug;"`
  - live smoke created 2 grants per MVP source.

## Stage 4: Client profiles і application history

Status: done

Ціль: зробити простий спосіб описувати клієнтів, проєкти та історію попередніх подач без Google Drive.

Що зробити:

- Створити формат client profile у `CSV`.
- Поля client profile:
  - name
  - country
  - sector
  - organization_type
  - technologies
  - product_description
  - risks
  - target_topics
  - excluded_topics
- Створити окремий `application_history.csv`.
- Поля application history:
  - client_name
  - grant_title
  - grant_source
  - program_name
  - application_date
  - result: won, lost, rejected, not_submitted, unknown
  - country
  - applicant_type
  - topics
  - project_summary
  - reusable_materials
  - similarity_weight
  - notes
- Додати loader, який читає локальні файли client profiles.
- Додати loader для application history.
- Додати збереження client profiles у database.
- Додати збереження application history у database.
- Важливо: результат попередньої подачі не використовується як негативний fit-сигнал.
- Якщо клієнт уже подавався на схожі гранти, це збільшує шанс вибору схожого гранта незалежно від того, виграли чи програли.

Результат етапу:

- Команда може вручну додавати клієнтів.
- Команда може вручну додавати історію попередніх подач.
- Matching pipeline має стабільне джерело client features.
- Matching pipeline має позитивний history signal для схожих грантів.
- Google Drive можна додати пізніше без зміни matching logic.

Фактично зроблено:

- Проаналізовано директорію `initial_grants/` як джерело реальних клієнтських грантових матеріалів.
- Визначено, що файли не є однорідним source для scraping:
  - частина файлів є meeting notes / transcripts;
  - частина є Q&A для доопрацювання заявок;
  - частина є concept notes або application drafts;
  - частина є feedback / grant strategy documents;
  - окремі PDF/JPG файли є legal або sensitive documents і не мають використовуватись для matching напряму.
- Зроблено manual curated extraction замість універсального scraper-а.
- Створено seed CSV для client profiles:
  - `data/manual_seed/client_profiles.manual.csv`
  - 5 клієнтів: `10guards`, `IS Academy`, `Intelswift`, `Versi Bionics`, `Vignette ID`.
- Створено seed CSV для application history / grant history:
  - `data/manual_seed/application_history.manual.csv`
  - 12 записів про попередні, заплановані або розглянуті гранти.
- Створено document inventory:
  - `data/manual_seed/document_inventory.manual.csv`
  - 18 файлів з `initial_grants/` класифіковано за типом документа, придатністю до matching і наявністю sensitive data.
- Для extracted records додано:
  - `source_documents`;
  - `confidence`;
  - `extraction_notes` або `notes`;
  - `similarity_weight` для application history.
- CSV-файли перевірено на коректний parsing:
  - `client_profiles.manual.csv`: 5 records;
  - `application_history.manual.csv`: 12 records;
  - `document_inventory.manual.csv`: 18 records.
- Додано CSV import module:
  - `grant_tool/client_import.py`.
- Додано loader для `client_profiles.manual.csv`.
- Додано loader для `application_history.manual.csv`.
- Реалізовано idempotent import:
  - client profiles оновлюються через `slug`;
  - application history оновлюється через natural key: `client_profile_id`, `grant_title`, `grant_source`, `program_name`.
- Додано repository methods:
  - `get_client_profile_by_slug`;
  - `get_client_profile_by_name`;
  - `upsert_application_history`.
- Додано CLI commands:
  - `grant-tool import-clients`;
  - `grant-tool import-application-history`;
  - `grant-tool import-manual-seed`.
- Import jobs створюють `JobRun` records:
  - `import_clients`;
  - `import_history`.
- Додано tests:
  - CSV helper parsing;
  - manual seed import;
  - repeated import without duplicates;
  - import job recording;
  - invalid application history result validation.

Перевірено:

- `poetry run python -m compileall grant_tool tests`
- `poetry run python -m unittest tests.test_stage2_repository tests.test_stage4_import -v`
- `poetry run python -m unittest discover -v`
- `poetry run grant-tool --help`
- `docker compose exec -T app alembic upgrade head`
- `docker compose exec -T app grant-tool import-manual-seed`
- Повторний `grant-tool import-manual-seed` не створює дублікати:
  - first import: 5 client profiles created, 12 application history records created;
  - second import: 5 client profiles updated, 12 application history records updated;
  - database counts після повторного import: 5 `client_profiles`, 12 `application_history`.

## Stage 5: Normalization і feature extraction

Status: done

Ціль: перетворити raw data у grant features, придатні для filtering і matching.

Що зробити:

- Детерміновано витягувати базові поля:
  - title
  - deadline
  - source URL
  - program
  - status
  - funding amount, якщо явно доступний
- Нормалізувати deadline до єдиного date format.
- Нормалізувати applicant types:
  - SME
  - startup
  - company
  - NGO
  - consortium
- Нормалізувати topics:
  - AI
  - defence
  - dual-use
  - innovation
  - community
  - business support
  - education
  - culture
  - humanitarian
- Додати LLM extraction для полів, які складно витягти правилами:
  - eligibility
  - applicant type
  - topics
  - risks
  - restrictions
  - short summary
- Зберігати confidence і evidence для LLM extraction.

Результат етапу:

- Кожен грант має normalized feature card.
- Система може дешево фільтрувати багато грантів.
- Глибший LLM analysis застосовується тільки там, де це потрібно.

Фактично зроблено:

- Додано package `grant_tool/extraction`.
- Додано `FeatureExtractionService`.
- Stage 5 deterministic enrichment автоматично виконується під час `IngestionService._save_fetched_grant`.
- Додано rerun CLI:
  - `grant-tool extract-features --limit 100`;
  - `grant-tool extract-features --source <source> --limit 20`;
  - `grant-tool extract-features --use-llm`.
- Додано `JobType.FEATURE_EXTRACTION`.
- Додано repository methods:
  - `list_grants_for_feature_extraction`;
  - `update_grant_features`.
- Нормалізуються:
  - title, включно з fallback із URL для generic titles;
  - summary;
  - deadline/status;
  - funding amount min/max/currency;
  - applicant types: `SME`, `startup`, `company`, `NGO`, `consortium`;
  - topics: `AI`, `defence`, `dual-use`, `innovation`, `community`, `business support`, `education`, `culture`, `humanitarian`;
  - countries/geography;
  - eligibility/restrictions/cofinancing/consortium/contact snippets.
- Заповнюються:
  - `extraction_method`;
  - `extraction_confidence`;
  - `extraction_metadata.fields`;
  - `extraction_metadata.feature_card`;
  - `needs_manual_review`;
  - `manual_review_reason`.
- Optional LLM extraction додано через `--use-llm`.
  - Якщо `OPENAI_API_KEY` не заданий, LLM step пропускається.
  - Prompt обмежує extraction тільки фактами з raw source text.
- Додано tests:
  - deterministic feature card;
  - generic title recovery/manual review;
  - ingestion integration;
  - rerun extraction job.

Перевірено:

- `poetry run python -m unittest tests.test_stage5_extraction -v`
- `poetry run python -m unittest`
- `poetry run python -m compileall grant_tool tests`
- `poetry run grant-tool --help`

### Stage 5 cleanup gate перед Stage 6

Статус: implemented; DB should be re-enriched before Stage 6 matching.

Після реального запуску `grant-tool ingest --all --limit 10` і
`grant-tool extract-features --limit 100 --use-llm` базова Stage 5 працює:
дані зберігаються, deterministic extraction виконується, LLM enrichment
запускається для вже збереженого raw text. Але DB metrics показали кілька
проблем якості, які краще закрити до Stage 6, інакше cheap filtering/matching
буде ранжувати частину grant records на слабких або noisy features.

Cleanup tasks:

1. Fix EU funding extraction:
   - не приймати internal IDs, reference numbers, checksums або topic codes як `funding_amount_text`;
   - витягувати funding тільки з явних budget/amount/value полів або надійних textual patterns;
   - якщо сума неочевидна, залишати funding empty і додавати evidence/manual review reason.
2. Fix Diia funding validation:
   - не приймати KVED/classification values типу `01.2` як суму фінансування;
   - валідні суми мають бути currency-like amount values або текстові ranges з контекстом гранту;
   - bad candidate values повинні йти в extraction metadata/debug, але не в normalized funding fields.
3. Improve status rules для Diia open-ended programs:
   - програми без явного deadline, але з активною сторінкою/умовами подачі, не мають автоматично ставати `unknown`;
   - додати rule для open-ended або active-until-changed programs;
   - зберігати reason у `extraction_metadata.fields.status`.
4. Reduce noisy default topics:
   - не додавати broad topics лише через generic words у page chrome/navigation;
   - topics мають базуватись на title, summary, eligibility, program description або LLM evidence;
   - краще менше topics з вищою якістю, ніж багато weak tags.
5. Rerun LLM enrichment:
   - після fixes очистити або пере-enrich existing rows;
   - запустити `docker compose exec app grant-tool extract-features --limit 100 --use-llm`;
   - перевірити, що LLM metadata і `extraction_method` коректно відображають LLM usage.
6. Перевірити DB metrics ще раз:
   - completeness по deadline/funding/currency/eligibility/applicant_types/topics/contact;
   - quality metrics по `unknown_status`, `needs_manual_review`, suspicious funding;
   - sample review по EU, Diia і Prostir records.

Exit criteria для переходу до Stage 6:

- EU більше не має obvious fake funding values з IDs/reference numbers.
- Diia більше не має classification codes у funding fields.
- Diia open-ended programs мають зрозумілий status або manual review reason.
- Topics стали менш noisy і краще пояснюються evidence.
- `extract-features --use-llm` проходить без failed rows на поточному dataset.
- DB metrics достатньо чисті для cheap filtering і shortlist scoring.

Фактично зроблено:

- Bumped `NORMALIZATION_VERSION` до `stage5-deterministic-v2`.
- EU funding extraction:
  - JSON budget payloads без `minContribution`/`maxContribution` більше не дають fake funding з IDs/reference numbers;
  - `20xx` years з deadline/context більше не можуть ставати funding amount;
  - якщо EU payload має `minContribution`/`maxContribution`, `funding_amount_text` формується як clean amount range, наприклад `EUR 15 000 000 - 25 000 000`.
- Diia funding validation:
  - KVED/classification values типу `01.2` відкидаються і не потрапляють у normalized funding fields;
  - валідні amount values типу `до 400 000` зберігаються.
- Diia status:
  - active finance pages без explicit deadline трактуються як open/open-ended;
  - broad word `заверш` більше не закриває програму без явної фрази про закриття прийому заявок.
- Topics cleanup:
  - taxonomy extraction використовує focused content text, а не весь raw payload/page metadata;
  - generic topics типу `гранти`, `фінансування`, `business` видаляються;
  - broad topic triggers `local` і `бізнес` зменшено, щоб не створювати noisy tags.
- Додано regression tests для EU fake IDs, EU deadline year, EU JSON budget range, Diia KVED, Diia open-ended status і noisy raw payload topics.

Перевірено:

- `poetry run python -m unittest tests.test_stage5_extraction -v`
- `poetry run python -m unittest`
- `poetry run python -m compileall grant_tool tests`
- `docker compose exec app grant-tool extract-features --limit 100`

Поточні DB metrics після deterministic rerun на 30 records:

- `diia-business`: total 10, unknown_status 0, suspicious_funding 0, no_topics 2.
- `eu-funding`: total 10, unknown_status 6, suspicious_funding 0, no_topics 8, manual_review 7.
- `prostir`: total 10, unknown_status 0, suspicious_funding 0, no_topics 0.

Висновок: Stage 5 cleanup прибрав головні parser bugs для funding/status. Перед production-quality Stage 6 все ще бажано rerun `extract-features --use-llm`, бо EU API records часто мають мало content для deterministic eligibility/topics.

## Stage 6: Cheap filtering і shortlist

Ціль: не аналізувати всі гранти глибоко, а спершу звузити список.

Що зробити:

- Додати hard filters:
  - grant active або upcoming
  - deadline не минув
  - країна / eligibility підходить
  - applicant type не конфліктує з client profile
  - немає очевидних exclusions
- Додати keyword scoring:
  - topics grant-а проти target topics клієнта
  - technologies клієнта проти title/summary/topics гранта
  - excluded topics зменшують score
- Додати application history scoring:
  - схожість нового гранта до попередніх подач клієнта збільшує score
  - result попередньої подачі не зменшує score
  - won/lost/rejected/not_submitted зберігається як context, але не як fit penalty
  - reusable materials збільшують score
- Додати shortlist threshold:
  - наприклад, брати тільки top N грантів на клієнта
  - або тільки гранти зі score вище мінімального порогу

Результат етапу:

- Система швидко відсікає нерелевантні гранти.
- Схожість до попередніх подач піднімає релевантні гранти вище у shortlist.
- LLM і vector similarity не витрачаються на весь датасет.

Статус реалізації Stage 6: done for MVP.

Фактично зроблено:

- Додано package `grant_tool/matching`.
- Додано `ShortlistMatchingService`.
- Додано `MATCHING_VERSION = stage6-shortlist-v1`.
- Додано CLI:
  - `grant-tool match`;
  - `grant-tool match --client <client-slug>`;
  - `grant-tool match --top-n 5 --min-score 0.20`;
  - `grant-tool match --grant-limit 50`.
- Додано repository methods:
  - `list_client_profiles`;
  - `list_grants_for_matching`;
  - `list_application_history_for_client`.
- Matching створює `MatchRun` зі status `success` і parameters.
- Results зберігаються у `grant_client_matches`.
- Для кожного match зберігаються:
  - `score`;
  - `rank`;
  - `hard_filter_passed`;
  - `filter_reasons`;
  - `keyword_score`;
  - `history_score`;
  - `manual_checks`;
  - `evidence`;
  - `match_metadata.score_breakdown`.

Hard filters:

- closed grants відсікаються;
- grants з deadline у минулому відсікаються;
- country mismatch відсікається;
- applicant type mismatch відсікається;
- explicit restriction conflict відсікається;
- training/tender/procurement/non-grant opportunity відсікається;
- company clients не отримують nonprofit-only grants навіть якщо source/LLM noisy applicant types додали `company`.

Soft handling:

- `unknown` status не блокує match, але додає manual check;
- missing deadline/country/applicant_types не блокує match, але додає manual checks;
- excluded topics знижують score;
- application history дає positive boost;
- `lost`, `rejected`, `not_submitted` не створюють penalty.

Scoring:

- final score = keyword score + application history boost + small extraction confidence bonus;
- vector score і LLM score залишаються `None` до Stage 7/8;
- low score records не зберігаються, якщо нижче `min_score`;
- top N зберігається окремо для кожного client profile.

Перевірено:

- `poetry run python -m unittest tests.test_stage6_matching -v`
- `poetry run python -m unittest`
- `poetry run python -m compileall grant_tool tests`
- `poetry run grant-tool match --help`
- `docker compose exec app grant-tool match --top-n 5 --min-score 0.20`

Docker smoke на поточній DB:

- clients: 5
- grants: 52
- evaluated: 260
- saved: 3
- filtered: 257

Висновок: Stage 6 працює як суворий cheap shortlist. Recall поки обмежений, але це очікувано до Stage 7 vector similarity.

Важливий принцип для Stage 6+:

- Поточні grants у локальній DB є випадковим sample, а не ground truth dataset.
- Не підганяти matching logic під конкретні grants, які зараз лежать у DB.
- Не додавати rules тільки тому, що вони покращують поточні 52 records.
- Додавати тільки generic rules, які мають сенс для багатьох джерел і майбутніх datasets.
- Якщо потрібні source-specific або language-specific евристики, виносити їх у конфігуровані rule sets з evidence, а не ховати як ad hoc logic.
- Stage 7 має будувати generic matching architecture: structured hard filters, semantic/vector similarity, history boost і explainable score breakdown.

## Stage 7: Vector similarity і matching score

Ціль: покращити matching між grant features і client features.

Що зробити:

- Створити текстове представлення grant profile:
  - title
  - summary
  - topics
  - eligibility
  - applicant types
  - restrictions
- Створити текстове представлення client profile:
  - sector
  - organization type
  - technologies
  - product description
  - target topics
  - risks
- Створити текстове представлення application history:
  - grant/program/funder
  - topics
  - applicant type
  - country/eligibility
  - project summary
  - reusable materials
- Додати embeddings для grants і clients.
- Додати embeddings або similarity text для application history records.
- Зберігати embeddings у PostgreSQL через `pgvector`.
- Розраховувати final score як комбінацію:
  - hard filter result
  - keyword score
  - vector similarity
  - application history similarity boost
  - reuse potential boost
- Зберігати score breakdown для dashboard.
- Не додавати penalty за lost applications.
- Якщо попередня подача була rejected або not_submitted, це може створювати note для ручної перевірки, але не знижує fit score.

Результат етапу:

- Matching стає більш гнучким, ніж тільки keywords.
- Попередні подачі допомагають знаходити схожі релевантні гранти навіть тоді, коли попередній результат був програшним.
- Dashboard може пояснювати, чому match отримав високий або низький score.

Статус реалізації Stage 7: done for MVP.

Фактично зроблено:

- Додано embedding columns у `grants`, `client_profiles`, `application_history`:
  - `embedding`;
  - `embedding_text`;
  - `embedding_model`;
  - `embedded_at`.
- Додано migration `20260521_0003_add_embedding_columns`.
- Додано package `grant_tool/embeddings`.
- Додано `EmbeddingService`.
- Додано profile text builders:
  - grant profile text;
  - client profile text;
  - application history profile text.
- Додано embedding providers:
  - `hash`: deterministic local provider для tests/offline smoke;
  - `openai`: real embeddings через OpenAI embeddings API.
- Додано CLI:
  - `grant-tool embed --target all --provider hash`;
  - `grant-tool embed --target grants --provider openai`;
  - `grant-tool match --use-vector`.
- `ShortlistMatchingService` тепер може рахувати `vector_score`, якщо embeddings існують.
- Якщо embeddings відсутні, matching fallback-иться до Stage 6 score.
- Vector layer не може погіршити Stage 6 fallback score:
  - final score використовує `max(stage6_score, vector_blended_score)`.
- `grant_client_matches.vector_score` заповнюється для vector runs.
- `match_metadata.score_breakdown` містить:
  - `keyword_score`;
  - `vector_score`;
  - `history_score`;
  - `stage6_fallback_score`;
  - `final_score`.
- `evidence.vector` містить similarity evidence.

Перевірено:

- `poetry run python -m unittest tests.test_stage7_embeddings -v`
- `poetry run python -m unittest`
- `poetry run python -m compileall grant_tool tests migrations`
- `poetry run grant-tool embed --help`
- `poetry run grant-tool match --help`
- `docker compose exec app alembic upgrade head`
- `docker compose exec app grant-tool embed --target all --provider hash --batch-size 16`
- `docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector`

Docker smoke на поточній DB:

- embedded grants: 52/52
- embedded clients: 5/5
- embedded application history: 12/12
- vector matching evaluated: 260 grant-client pairs
- saved: 3
- filtered: 257

Важливо:

- `hash` embeddings потрібні тільки для deterministic local tests/smoke і не є якісною semantic model.
- Для реального semantic matching треба запускати `--provider openai`.
- Stage 7 не підганяє matching під поточні grants; profile text і scoring generic.

## Stage 8: LLM explanations і risk notes

Ціль: використовувати AI там, де він найбільш корисний для людини.

Що зробити:

- Для top matches генерувати:
  - коротке пояснення, чому грант підходить клієнту
  - ризики
  - обмеження
  - що треба перевірити вручну
- LLM prompt має отримувати тільки:
  - normalized grant card
  - client feature card
  - relevant application history records
  - score breakdown
- LLM не має самостійно вирішувати, чи є match.
- LLM не має трактувати lost application як доказ поганого fit.
- Зберігати LLM output у `GrantClientMatch`.

Результат етапу:

- Користувач бачить не тільки score, а й практичне пояснення.
- Report стає корисним для грантрайтера або менеджера.

Статус реалізації Stage 8: done for MVP.

Фактично зроблено:

- Додано package `grant_tool/explanations`.
- Додано `MatchExplanationService`.
- Додано CLI:
  - `grant-tool explain-matches --match-run-id <match-run-id> --limit 20 --provider openai`;
  - `grant-tool explain-matches --limit 20 --provider rule`.
- Команда за замовчуванням бере latest `MatchRun`, якщо `--match-run-id` не передано.
- Prompt/payload отримує тільки:
  - normalized grant profile;
  - client profile;
  - relevant application history;
  - saved deterministic/vector score breakdown;
  - existing evidence і manual checks.
- LLM не приймає match decision з нуля; він пояснює вже збережений result.
- `lost`, `rejected`, `not_submitted` history не трактуються як негативний fit-сигнал.
- Output записується у `grant_client_matches`:
  - `explanation`;
  - `risks_text`;
  - `manual_checks`;
  - `llm_score`;
  - `match_metadata.llm_explanation`.
- Додано deterministic `rule` provider для local smoke/tests без OpenAI API.
- Додано OpenAI provider через `OPENAI_API_KEY` і `LLM_MODEL`.

Перевірено:

- `poetry run python -m unittest tests.test_stage8_explanations -v`
- `poetry run python -m unittest`
- `poetry run python -m compileall grant_tool tests migrations`
- `poetry run grant-tool explain-matches --help`
- `docker compose exec app grant-tool explain-matches --match-run-id e27c8092-9cdf-47b9-a1f4-26788a03718b --limit 5 --provider rule`
- `docker compose exec app grant-tool explain-matches --match-run-id e27c8092-9cdf-47b9-a1f4-26788a03718b --limit 3 --provider openai`

Docker smoke на поточній DB:

- rule provider: processed 5, updated 5, failed 0.
- OpenAI provider: processed 3, updated 3, failed 0.
- OpenAI model used: `gpt-4.1-mini`.
- Output saved into `grant_client_matches`.

Важливо:

- Stage 8 не підганяє логіку під поточну DB.
- LLM explanation не має змінювати `score`; score генерується Stage 6/7.
- `llm_score` зараз означає confidence/quality of explanation, а не final match score.

## Stage 9: Web dashboard

Ціль: зробити перший usable interface для перегляду грантів, клієнтів і matches.

Що зробити:

- Додати головну сторінку з короткою статистикою:
  - кількість грантів
  - нові гранти
  - оновлені гранти
  - кількість клієнтів
  - кількість matches
- Додати Grants page:
  - список грантів
  - filters
  - source URL
  - deadline
  - status
  - topics
  - applicant types
  - confidence
- Додати Client profiles page:
  - список клієнтів
  - перегляд feature card
- Додати Matches page:
  - top grants per client
  - top clients per grant
  - score breakdown
  - explanation
  - risks
  - manual review status
- Додати Report page:
  - нові гранти
  - оновлені гранти
  - рекомендовані matches
  - manual check items

Результат етапу:

- Інструментом можна користуватись через браузер.
- Не потрібно працювати тільки через CLI або database.

## Stage 10: Daily report і automation

Ціль: автоматизувати регулярне оновлення і щоденний report.

Що зробити:

- Додати scheduler:
  - ingestion кожні 6-12 годин
  - daily report раз на день
- Додати worker command для ручного запуску:
  - ingest all sources
  - reload client profiles
  - run matching
  - generate report
- Зробити jobs idempotent:
  - повторний запуск не створює дублікати
  - оновлені grants перезаписують normalized fields
  - старі matches можна позначати як outdated
- Логувати помилки connector-ів окремо, щоб один сайт не ламав всю систему.

Результат етапу:

- Система сама оновлює базу грантів.
- Раз на день формується report.
- Користувач заходить у dashboard і бачить актуальний стан.

## Stage 11: Розширення після MVP

Ціль: додати ширший список джерел і Google Drive після стабілізації core pipeline.

Джерела для наступних етапів:

- Grant Market
- Chas Zmin
- GrantSense
- EUFundingPortal.eu
- fundsforngos.org
- OpportunityDesk
- GrantForward
- NIPO дайджести
- Hromady.org

Що додати пізніше:

- Google Drive connector для client/project docs.
- Google Sheets import/export.
- Authentication для dashboard.
- Manual approval workflow.
- Email або Slack notifications.
- Export report у PDF або Google Docs.

Результат етапу:

- MVP перетворюється на повноцінний internal grant intelligence tool.
- Нові джерела додаються через той самий connector pattern.
