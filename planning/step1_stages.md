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
