# Реалізований MVP: AI Grant Matching Tool

## Мета MVP

MVP створює локальний web-інструмент для збору грантових можливостей, нормалізації даних, порівняння грантів із профілями клієнтів і перегляду результатів у dashboard.

Інструмент працює як внутрішня система для grant research:

- збирає гранти з перших налаштованих джерел;
- зберігає raw дані для перевірки;
- створює очищені записи грантів;
- імпортує профілі клієнтів і попередню історію заявок;
- витягує ознаки грантів;
- рахує shortlist matches;
- додає vector similarity;
- генерує пояснення для top matches;
- показує все в dashboard.

## Scope Реалізованого MVP

Поточний MVP покриває 4 джерела:

- EU Funding & Tenders Portal;
- Prostir grants;
- GURT grants;
- Diia Business finance programs.

Примітка після завершення Search / Link Extraction stage: цей документ описує саме історичний MVP scope. Поточний search layer розширений на всі implementable надані джерела і задокументований окремо в `docs/plan/search/implemented_for_search.md` та `docs/initial_sources.md`.

Клієнтські дані у MVP подаються через локальні CSV-файли:

- `data/manual_seed/client_profiles.manual.csv`;
- `data/manual_seed/application_history.manual.csv`;
- `data/manual_seed/document_inventory.manual.csv`.

`document_inventory.manual.csv` зараз використовується як ручний reference file і не імпортується CLI-командою.

## Загальний Потік Даних

Реалізований flow виглядає так:

```text
source definitions
  -> source connectors
  -> fetched grants
  -> deterministic feature extraction
  -> raw snapshots + normalized grants
  -> client profiles + application history
  -> matching
  -> embeddings/vector matching
  -> explanations
  -> dashboard
```

Важлива ідея: система не довіряє тільки cleaned fields. Вона зберігає raw source data поруч із нормалізованим записом гранту, щоб пізніше можна було перевірити, що саме прийшло з джерела.

## Stage 1: База Проєкту І Локальний Запуск

Статус: реалізовано.

На цьому етапі створено технічну основу проєкту:

- Python package structure `grant_tool`;
- FastAPI application;
- root dashboard route `/`;
- health endpoint `/api/v1/health`;
- Dockerfile;
- Docker Compose setup;
- PostgreSQL з `pgvector`;
- Redis;
- `.env.example`;
- `.dockerignore`;
- Poetry dependency setup;
- базові команди запуску в документації.

Основний локальний запуск:

```bash
docker compose up --build
```

Docker Compose піднімає:

- app;
- PostgreSQL;
- Redis;
- one-shot `migrate` service.

У `docker-compose.yml` також є profile-сервіси `worker` і `beat`, але регулярна фонова автоматизація не є частиною реалізованого MVP flow. Основний MVP запускається через CLI-команди і dashboard.

`migrate` виконує:

```bash
alembic upgrade head
grant-tool seed-sources
```

Тобто після старту база має актуальну schema і seeded MVP sources.

## Stage 2: Data Model І Database Layer

Статус: реалізовано.

Створено SQLAlchemy database layer у `grant_tool/db`.

Основні моделі:

- `Source`;
- `RawGrantSnapshot`;
- `Grant`;
- `ClientProfile`;
- `ApplicationHistory`;
- `JobRun`;
- `MatchRun`;
- `GrantClientMatch`;
- `Report`.

### `sources`

Таблиця `sources` описує джерела грантів.

Ключові поля:

- `name`;
- `slug`;
- `base_url`;
- `list_url`;
- `api_url`;
- `feed_url`;
- `sitemap_url`;
- `access_strategy`;
- `requires_browser`;
- `enabled`;
- `rate_limit_seconds`;
- `notes`;
- `source_metadata`.

`access_strategy` може бути:

- `api`;
- `wp_rest`;
- `rss`;
- `sitemap_html`;
- `html`;
- `browser`;
- `manual`.

### `raw_grant_snapshots`

Це audit/debug таблиця для оригінальних даних.

Ключові поля:

- `source_id`;
- `source_record_id`;
- `source_url`;
- `fetched_at`;
- `http_status`;
- `content_type`;
- `raw_title`;
- `raw_summary`;
- `raw_text`;
- `raw_html`;
- `raw_payload`;
- `content_hash`;
- `metadata`.

Для API-джерел основне поле - `raw_payload`.

Для HTML/RSS джерел важливі:

- `raw_html`;
- `raw_text`;
- `source_url`.

### `grants`

Це головна таблиця очищених грантів.

Ключові поля:

- `source_id`;
- `latest_raw_snapshot_id`;
- `source_record_id`;
- `source_url`;
- `application_url`;
- `title`;
- `summary`;
- `description_text`;
- `language`;
- `status`;
- `published_at`;
- `opens_at`;
- `deadline_at`;
- `deadline_text`;
- `program_name`;
- `funder_name`;
- `opportunity_type`;
- `support_type`;
- `funding_amount_min`;
- `funding_amount_max`;
- `funding_amount_text`;
- `currency`;
- `geography_text`;
- `countries`;
- `regions`;
- `eligibility_text`;
- `applicant_types`;
- `topics`;
- `keywords`;
- `restrictions_text`;
- `cofinancing_required`;
- `cofinancing_text`;
- `consortium_required`;
- `consortium_text`;
- `implementation_period_text`;
- `contact_text`;
- `documents`;
- `source_metadata`;
- `extraction_method`;
- `extraction_confidence`;
- `extraction_metadata`;
- `needs_manual_review`;
- `manual_review_reason`;
- `embedding`;
- `embedding_text`;
- `embedding_model`;
- `embedded_at`.

Обов'язковими для нормалізованого гранту є тільки технічні мінімуми: source, URL, title і status. Більшість business fields optional, бо різні сайти дають різну якість даних.

## Stage 2.5: Job Tracking І Source Seeding

Статус: реалізовано.

Додано `JobRun`, щоб кожен запуск мав audit trail.

`job_runs` зберігає:

- `job_type`;
- `source_id`;
- `status`;
- `started_at`;
- `finished_at`;
- `processed_count`;
- `created_count`;
- `updated_count`;
- `skipped_count`;
- `failed_count`;
- `error_message`;
- `job_metadata`.

Реалізовані job statuses:

- `pending`;
- `running`;
- `success`;
- `failed`;
- `partial`.

Додано seed для MVP sources:

- `eu-funding`;
- `prostir`;
- `diia-business`;
- `gurt`.

CLI:

```bash
grant-tool seed-sources
grant-tool jobs list
grant-tool jobs show <job-id>
```

Повторний `seed-sources` оновлює sources, а не створює дублікати.

## Stage 3: Ingestion Connector Framework І MVP Connectors

Статус: реалізовано.

Ingestion зроблено як спільний framework із source-specific connectors.

Основні частини:

- `BaseConnector`;
- `FetchedGrant`;
- `NormalizedGrantDraft`;
- `ConnectorResult`;
- `ConnectorError`;
- shared `HttpClient`;
- content hashing;
- `IngestionService`;
- source-specific connector classes.

### Як Працює Ingestion

1. `IngestionService` бере `Source` з database.
2. По `source_slug` знаходить потрібний connector.
3. Connector отримує list/feed/API data.
4. Connector формує список `FetchedGrant`.
5. Для кожного grant система запускає deterministic enrichment.
6. Потім зберігає `RawGrantSnapshot`.
7. Після цього робить upsert у `grants`.
8. `JobRun` counters оновлюються після кожного запису.
9. Якщо один detail page падає, весь ingestion job не має падати повністю.

Команди:

```bash
grant-tool ingest --source eu-funding --limit 20
grant-tool ingest --source prostir --limit 20
grant-tool ingest --source diia-business --limit 20
grant-tool ingest --source gurt --limit 20
grant-tool ingest --all --limit 20
```

### EU Funding Connector

Файл: `grant_tool/ingestion/connectors/eu_funding.py`.

Стратегія:

- API access;
- endpoint `https://api.tech.ec.europa.eu/search-api/prod/rest/search`;
- `apiKey=SEDIA`;
- JSON payload зберігається в `raw_payload`;
- normalized fields формуються з API metadata.

Витягуються:

- title;
- source URL;
- source record ID;
- summary;
- description;
- status;
- opening date;
- deadline;
- program/framework;
- funder;
- support type;
- budget/funding text;
- keywords/topics.

### Prostir Connector

Файл: `grant_tool/ingestion/connectors/prostir.py`.

Стратегія:

- RSS feed для discovery;
- HTML detail pages для повного тексту;
- fallback на list page, якщо RSS не повернув items.

Процес:

```text
RSS item -> detail page -> raw_html/raw_text -> normalized grant
```

Витягуються:

- title;
- link/source URL;
- publication date;
- summary;
- full text;
- deadline;
- funding text;
- documents;
- status.

### Diia Business Connector

Файл: `grant_tool/ingestion/connectors/diia_business.py`.

Стратегія:

- public frontend API як основний спосіб;
- sitemap/list + HTML detail pages як fallback.

Основний API:

```text
https://api.business.diia.gov.ua/api/front/finance
```

Detail API:

```text
https://api.business.diia.gov.ua/api/front/finance/service/<slug>
```

Витягуються:

- title;
- description;
- company/funder name;
- category/program;
- attributes;
- deadline/program term;
- amount;
- currency;
- geography;
- eligibility;
- support type;
- application URL.

Diia Business містить не тільки класичні grants, а й ширші finance programmes:

- grants;
- loans;
- guarantees;
- leasing;
- factoring;
- tender support;
- other finance programmes.

### GURT Connector

Файл: `grant_tool/ingestion/connectors/gurt.py`.

Стратегія:

- HTML list page;
- HTML detail pages;
- conservative parsing.

Процес:

```text
list page -> links under /news/grants/ -> detail HTML -> clean text -> normalized grant
```

Витягуються:

- title;
- source URL;
- summary;
- full text;
- deadline;
- status;
- funding text;
- documents.

## Stage 4: Client Profiles І Application History

Статус: реалізовано.

Дані клієнтів імпортуються з локальних CSV.

Файли:

- `data/manual_seed/client_profiles.manual.csv`;
- `data/manual_seed/application_history.manual.csv`;
- `data/manual_seed/document_inventory.manual.csv`.

Імпортуються тільки client profiles і application history. `document_inventory.manual.csv` залишається ручним інвентарем документів і не читається CLI-командами.

CLI:

```bash
grant-tool import-manual-seed
grant-tool import-clients --file data/manual_seed/client_profiles.manual.csv
grant-tool import-application-history --file data/manual_seed/application_history.manual.csv
```

### Client Profiles

Зберігаються у `client_profiles`.

Ключові поля:

- `name`;
- `slug`;
- `country`;
- `sector`;
- `organization_type`;
- `technologies`;
- `product_description`;
- `risks`;
- `target_topics`;
- `excluded_topics`;
- `previous_submissions_summary`;
- `source_type`;
- `source_uri`;
- `profile_metadata`;
- `enabled`.

### Application History

Зберігається у `application_history`.

Ключові поля:

- `client_profile_id`;
- `grant_id`;
- `client_name`;
- `grant_title`;
- `grant_source`;
- `program_name`;
- `application_date`;
- `result`;
- `country`;
- `applicant_type`;
- `topics`;
- `project_summary`;
- `reusable_materials`;
- `similarity_weight`;
- `notes`;
- `history_metadata`.

Allowed `result` values:

- `won`;
- `lost`;
- `rejected`;
- `not_submitted`;
- `unknown`.

Попередні заявки використовуються як позитивний relevance signal. `lost`, `rejected` і `not_submitted` не зменшують score, але можуть створювати manual review notes.

## Stage 5: Normalization І Feature Extraction

Статус: реалізовано.

Додано `grant_tool/extraction/FeatureExtractionService`.

Feature extraction запускається:

- автоматично під час ingestion перед `Grant` upsert;
- вручну для вже збережених grants.

CLI:

```bash
grant-tool extract-features --limit 100
grant-tool extract-features --source prostir --limit 20
grant-tool extract-features --limit 100 --use-llm
```

### Deterministic Extraction

За замовчуванням використовується deterministic extraction без LLM.

Вона нормалізує:

- title;
- summary;
- deadline;
- status;
- funding amount min/max/text;
- currency;
- opportunity type;
- support type;
- applicant types;
- topics;
- countries/geography;
- eligibility snippets;
- restrictions;
- cofinancing;
- consortium requirement;
- implementation period;
- contact snippets;
- documents;
- extraction confidence;
- feature card;
- manual review reason.

Applicant type rules:

- `SME`;
- `startup`;
- `company`;
- `NGO`;
- `consortium`.

Topic rules:

- `AI`;
- `defence`;
- `dual-use`;
- `innovation`;
- `community`;
- `business support`;
- `education`;
- `culture`;
- `humanitarian`.

### Optional LLM Extraction

LLM enrichment доступний через:

```bash
grant-tool extract-features --use-llm
```

Потрібен `OPENAI_API_KEY`.

LLM використовується тільки для доповнення missing/unclear fields, наприклад:

- summary;
- eligibility;
- restrictions;
- applicant types;
- topics.

LLM не має вигадувати дані. Він отримує raw source text і має витягувати тільки факти, які підтримуються source evidence.

### Cleanup Pass

Перед matching було реалізовано cleanup pass:

- EU IDs/reference numbers більше не приймаються як funding amount;
- EU JSON contribution fields можуть формувати clean funding range;
- Diia KVED/classification values не приймаються як funding;
- Diia open-ended finance pages отримують open/open-ended status;
- generic topics чистяться;
- suspicious fields ведуть до lower confidence або manual review.

Поточна normalization version:

```text
stage5-deterministic-v2
```

## Stage 6: Shortlist Matching

Статус: реалізовано для MVP.

Додано `grant_tool/matching/ShortlistMatchingService`.

CLI:

```bash
grant-tool match --top-n 5 --min-score 0.20
grant-tool match --client intelswift --top-n 10
```

Matching створює `MatchRun` і зберігає результати в `grant_client_matches`.

### Matching Logic

Система використовує:

- hard filters;
- keyword/topic scoring;
- applicant type fit;
- sector fit;
- excluded topic penalty;
- application history boost;
- reusable materials boost;
- manual checks.

Hard filters відсікають:

- expired/closed grants;
- country mismatch;
- applicant type mismatch;
- explicit restriction conflict;
- training/tender/procurement/non-grant opportunities;
- nonprofit-only grants для company clients.

Score breakdown зберігається у `match_metadata`.

Evidence зберігається у `evidence`.

Manual checks зберігаються у `manual_checks`.

## Stage 7: Embeddings І Vector Similarity

Статус: реалізовано для MVP.

Додано:

- embedding columns у `grants`;
- embedding columns у `client_profiles`;
- embedding columns у `application_history`;
- migration `20260521_0003_add_embedding_columns`;
- `grant_tool/embeddings/EmbeddingService`.

Поля:

- `embedding`;
- `embedding_text`;
- `embedding_model`;
- `embedded_at`.

CLI:

```bash
grant-tool embed --target all --provider hash
grant-tool embed --target grants --provider hash
grant-tool embed --target clients --provider hash
grant-tool embed --target history --provider hash
grant-tool embed --target all --provider openai
```

Providers:

- `hash` - deterministic local provider для tests/smoke;
- `openai` - реальні semantic embeddings.

Vector matching:

```bash
grant-tool match --top-n 5 --min-score 0.20 --use-vector
```

Vector layer не може погіршити Stage 6 fallback score. Final score використовує кращий результат між Stage 6 і vector-blended score.

## Stage 8: Match Explanations І Risk Notes

Статус: реалізовано для MVP.

Додано `grant_tool/explanations/MatchExplanationService`.

CLI:

```bash
grant-tool explain-matches --limit 20 --provider rule
grant-tool explain-matches --limit 20 --provider openai
grant-tool explain-matches --match-run-id <match-run-id> --limit 20 --provider openai
```

Providers:

- `rule` - deterministic provider для локальних перевірок;
- `openai` - LLM provider для реальних пояснень.

Stage 8 бере вже збережений `MatchRun` і top matches. Він не рахує match заново.

Payload для explanation містить:

- normalized grant profile;
- client profile;
- relevant application history;
- score breakdown;
- evidence;
- manual checks.

LLM не приймає рішення, чи є match. Він пояснює вже збережений результат.

Output записується у `grant_client_matches`:

- `explanation`;
- `risks_text`;
- `manual_checks`;
- `llm_score`;
- `match_metadata.llm_explanation`.

## Stage 9: Web Dashboard

Статус: реалізовано для MVP.

Додано:

- package `grant_tool/dashboard`;
- `DashboardService`;
- dashboard routes;
- Jinja templates;
- static CSS.

Routes:

- `/`;
- `/grants`;
- `/clients`;
- `/matches`;
- `/report`;
- `/static/css/dashboard.css`.

Templates:

- `grant_tool/templates/dashboard/base.html`;
- `grant_tool/templates/dashboard/overview.html`;
- `grant_tool/templates/dashboard/grants.html`;
- `grant_tool/templates/dashboard/clients.html`;
- `grant_tool/templates/dashboard/matches.html`;
- `grant_tool/templates/dashboard/report.html`.

CSS:

- `grant_tool/static/css/dashboard.css`.

### Overview Page

Показує:

- total/open/new grants;
- manual review queue;
- clients;
- matches;
- explained matches;
- source distribution;
- status distribution;
- latest jobs;
- recent grants;
- top matches by client.

### Grants Page

Показує grant cards із:

- source;
- source URL;
- status;
- deadline;
- funding;
- applicant types;
- topics;
- extraction confidence;
- manual review marker.

Filters:

- search;
- source;
- status;
- topic;
- manual review.

### Clients Page

Показує client feature cards:

- country;
- organization type;
- sector;
- technologies;
- target topics;
- history count;
- embedding model;
- risks.

### Matches Page

Показує top matches із:

- final score;
- rank;
- keyword score;
- vector score;
- history score;
- LLM score;
- explanation;
- risks;
- manual checks;
- source link.

### Report Page

Показує working view:

- recent grants;
- top matches by client;
- manual check queue;
- latest saved report, якщо він є в DB.

Dashboard є read-only layer. Він не змінює extraction або matching logic.

## Основні Команди MVP

Повний локальний smoke flow:

```bash
docker compose up -d --build
docker compose exec app grant-tool import-manual-seed
docker compose exec app grant-tool ingest --all --limit 20
docker compose exec app grant-tool extract-features --limit 100
docker compose exec app grant-tool embed --target all --provider hash
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
docker compose exec app grant-tool explain-matches --limit 20 --provider rule
```

Відкрити dashboard:

```text
http://localhost:8000/
```

OpenAI flow:

```bash
docker compose exec app grant-tool extract-features --limit 100 --use-llm
docker compose exec app grant-tool embed --target all --provider openai
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
docker compose exec app grant-tool explain-matches --limit 20 --provider openai
```

## Що Було Перевірено

Покрито перевірками:

- repository layer;
- source seeding;
- job lifecycle;
- ingestion connectors;
- fixture-based parsers;
- manual CSV import;
- deterministic extraction;
- matching;
- embeddings;
- explanations;
- dashboard smoke.

Основні тестові команди:

```bash
poetry run python -m unittest
poetry run python -m compileall grant_tool tests migrations
```

Docker smoke включав:

- migrations;
- seed sources;
- import manual seed;
- ingestion;
- feature extraction;
- embedding generation;
- matching;
- explanations;
- dashboard HTTP pages.

У репозиторії є Docker Compose profile-сервіси для `worker` і `beat`, але вони залишаються інфраструктурними заготовками для наступних етапів, а не завершеною автоматизацією MVP.
