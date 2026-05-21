# План MVP: AI Grant Matching Tool

## Коротко

Створити локальний Docker-based web dashboard, який збирає гранти з MVP-джерел, нормалізує дані, витягує відсутні features через LLM, порівнює гранти з профілями клієнтів і генерує щоденний report.

MVP-джерела:

- EU Funding & Tenders Portal
- Prostir grants
- GURT grants
- Diia Business finance programs

Профілі клієнтів у першій версії:

- ручні `YAML` або `CSV` файли
- Google Drive інтеграція переноситься на наступний етап

## Основні зміни

- Створити директорію `planning/`.
- Додати файл `planning/plan.md` з цим планом.
- Побудувати Python web stack:
  - `FastAPI` backend
  - dashboard через `Jinja2` + легкі HTMX-взаємодії
  - `PostgreSQL` + `pgvector`
  - Docker Compose для app, database, Redis, one-shot migrate service, worker і scheduler
  - змінити Python target з `^3.14` на стабільний `^3.12`, якщо немає причини залишати 3.14

## Data Model

Додати базові сутності:

- `Source`
  - джерело грантів
  - тип конектора
  - налаштування збору

- `RawGrant`
  - raw payload або HTML snapshot
  - source URL
  - fetch timestamp
  - checksum
  - source-specific ID, якщо є
  - raw text / raw HTML
  - raw metadata

- `JobRun`
  - операційний запис запуску ingestion/import/matching/report job
  - job type
  - source, якщо job source-specific
  - status: pending, running, success, failed, partial
  - started/finished timestamps
  - processed/created/updated/skipped/failed counters
  - error message
  - job metadata JSON

- `Grant`
  - title
  - summary
  - description text
  - deadline
  - deadline text
  - program
  - funder
  - status
  - countries / eligibility
  - regions / geography text
  - applicant types: SME, startup, company, NGO, consortium
  - topics: AI, defence, dual-use, innovation тощо
  - opportunity type / support type
  - funding amount min/max/text
  - currency
  - restrictions
  - cofinancing requirements
  - consortium requirements
  - application URL
  - documents
  - source URL
  - source metadata JSON
  - extraction confidence
  - extraction metadata JSON
  - needs manual review

- `ClientProfile`
  - назва клієнта
  - країна
  - сектор
  - тип організації
  - технологія / продукт
  - ризики

- `ApplicationHistory`
  - клієнт
  - грант / програма / донор, куди вже подавались
  - дата подачі, якщо відома
  - результат подачі: won, lost, rejected, not_submitted, unknown
  - теми
  - тип заявника
  - країна / eligibility
  - короткий опис проєкту
  - reusable materials
  - similarity weight
  - notes

- `MatchRun` і `GrantClientMatch`
  - hard-filter result
  - keyword score
  - vector similarity score
  - application history boost
  - reuse potential boost
  - final score
  - LLM explanation
  - risks
  - manual review status

- `Report`
  - дата генерації
  - нові / оновлені гранти
  - top matches
  - rendered HTML/Markdown output

## Ingestion Pipeline

- Перед конкретними source connectors додати shared connector framework:
  - `BaseConnector`
  - `FetchedGrant`
  - `FetchedDetail`
  - `NormalizedGrantDraft`
  - `ConnectorResult`
  - shared HTTP client з user-agent, timeout, limited retries і rate limit
  - content hashing для raw snapshots
  - common ingestion service, який зберігає raw data перед normalized upsert
- Перед першим ingestion додати source seeding для MVP sources:
  - EU Funding & Tenders Portal
  - Prostir grants
  - GURT grants
  - Diia Business finance programs
- Кожен ingestion запуск створює `JobRun` і оновлює counters/status.
- Якщо один grant/detail page падає, connector не має ламати весь ingestion job.
- Для EU Funding & Tenders Portal спочатку перевірити можливість роботи через офіційний/API-style доступ.
- Якщо стабільного публічного API недостатньо, ізолювати EU connector і зробити fallback на контрольоване structured extraction зі сторінок пошуку/details.
- Для Prostir, GURT і Diia:
  - спочатку шукати RSS/API/структуровані endpoints
  - якщо їх немає, використовувати polite HTML parsing із source-specific selectors
- Кожен fetch має зберігати raw data перед нормалізацією.
- Дедуплікація через source URL, source ID і checksum.
- Повторний запуск ingestion не має створювати дублікати.
- Реалізовувати MVP connectors по черзі:
  - спочатку EU Funding API connector;
  - потім Prostir RSS + detail HTML connector;
  - потім Diia Business sitemap/list + detail HTML connector;
  - потім GURT HTML list/detail connector.
- Для кожного connector додати fixture-based parser tests без обов'язкового live internet.

Статус реалізації Stage 3: done.

- Додано shared connector framework у `grant_tool/ingestion`.
- Додано connectors для EU Funding, Prostir, Diia Business і GURT.
- Додано CLI `grant-tool ingest --source <source> --limit 20` і `grant-tool ingest --all --limit 20`.
- Кожен ingestion запуск створює `JobRun`, зберігає `RawGrantSnapshot` і робить normalized `Grant` upsert.
- Parser tests працюють на local fixtures без live internet.
- Live smoke перевірено з conservative `--limit 2` для кожного MVP source.

## Feature Extraction

Статус реалізації Stage 5: done; cleanup pass перед Stage 6 implemented.

- Детерміноване витягування для:
  - title
  - deadline
  - source URL
  - status
  - funding amount, якщо поле явно доступне

- LLM extraction для:
  - eligibility
  - applicant type
  - topics
  - risks
  - restrictions
  - короткого summary

- Для кожного LLM extraction зберігати:
  - extracted value
  - confidence
  - evidence snippet або raw field
  - модель, якою було зроблено extraction

- LLM налаштовується через environment variables:
  - `OPENAI_API_KEY`
  - `LLM_MODEL`
  - `EMBEDDING_MODEL`

Фактично зроблено:

- Додано package `grant_tool/extraction`.
- Додано `FeatureExtractionService`.
- Ingestion автоматично запускає deterministic Stage 5 enrichment перед `Grant` upsert.
- Додано CLI:
  - `grant-tool extract-features --limit 100`
  - `grant-tool extract-features --source <source> --limit 20`
  - `grant-tool extract-features --use-llm`
- Додано `feature_extraction` job type для rerun extraction jobs.
- Deterministic extraction нормалізує:
  - title fallback із URL для generic titles;
  - summary;
  - deadline/status;
  - funding amount min/max/currency;
  - applicant types: `SME`, `startup`, `company`, `NGO`, `consortium`;
  - topics: `AI`, `defence`, `dual-use`, `innovation`, `community`, `business support`, `education`, `culture`, `humanitarian`;
  - countries/geography;
  - eligibility/restrictions/cofinancing/consortium/contact snippets;
  - `extraction_confidence`;
  - `extraction_metadata.fields` evidence;
  - `extraction_metadata.feature_card`.
- Optional LLM extraction uses `OPENAI_API_KEY`/`LLM_MODEL` and is disabled by default.
- Tests додано у `tests/test_stage5_extraction.py`.

Stage 5 cleanup pass перед Stage 6:

- Fix EU funding extraction:
  - не зберігати IDs/reference numbers/topic codes як grant funding;
  - funding брати тільки з надійних amount/budget fields або textual evidence.
- Fix Diia funding validation:
  - не приймати KVED/classification values типу `01.2` як суму;
  - suspicious values залишати тільки в metadata/debug або manual review reason.
- Improve status rules для Diia open-ended programs:
  - active pages без explicit deadline мають отримувати зрозумілий active/open-ended status або manual review reason.
- Reduce noisy default topics:
  - topics мають базуватись на grant content/evidence, не на generic page chrome.
- Rerun LLM enrichment:
  - `docker compose exec app grant-tool extract-features --limit 100 --use-llm`.
- Перевірити DB metrics:
  - completeness;
  - `unknown_status`;
  - `needs_manual_review`;
  - suspicious funding;
  - sample review по EU, Diia і Prostir.

Фактично implemented:

- `NORMALIZATION_VERSION = stage5-deterministic-v2`.
- EU IDs/reference numbers/deadline years більше не стають funding amounts.
- EU JSON `minContribution`/`maxContribution` формує clean funding range text.
- Diia KVED/classification values типу `01.2` відкидаються з funding fields.
- Diia active finance pages без deadline отримують open/open-ended status.
- Topics extraction більше не бере raw payload/page metadata як джерело default topics; generic topics чистяться.
- Regression tests додані у `tests/test_stage5_extraction.py`.

Після deterministic rerun на поточній DB:

- `diia-business`: unknown_status 0, suspicious_funding 0.
- `eu-funding`: suspicious_funding 0, але багато records все ще потребують manual review/LLM через слабкий content з API.
- `prostir`: без obvious cleanup blockers.

Stage 6 можна починати після rerun `extract-features --use-llm`, щоб filtering і shortlist scoring мали кращі eligibility/topics для EU records.

## Matching

Статус реалізації Stage 6: done for MVP.

- Спочатку hard filters:
  - активний або upcoming deadline
  - країна / geography
  - тип заявника
  - очевидні exclusions

- Потім keyword/topic scoring:
  - AI
  - defence
  - dual-use
  - innovation
  - NGO
  - SME
  - startup
  - інші теми з client profile

- Потім vector similarity:
  - embedding нормалізованого grant description
  - embedding client/project profile

- Потім application history boost:
  - якщо клієнт раніше подавався на схожі гранти, score збільшується
  - результат попередньої подачі не зменшує score
  - lost application все одно означає, що грант міг бути релевантним
  - rejected/not_submitted не є негативним fit-сигналом, але може створити manual review note
  - reuse potential збільшує score, якщо можна використати попередні матеріали

- LLM використовується для:
  - пояснення top matches
  - формулювання ризиків
  - списку того, що треба перевірити вручну

- LLM не має бути єдиним джерелом рішення про match.
- Попередні подачі на схожі гранти є позитивним relevance signal незалежно від win/loss result.

Фактично Stage 6 implemented:

- Додано `grant_tool/matching/ShortlistMatchingService`.
- Додано CLI `grant-tool match`.
- Results зберігаються у `grant_client_matches`.
- Кожен запуск створює `MatchRun`.
- Score breakdown зберігається у `match_metadata`.
- Evidence зберігається у `evidence`.
- `manual_checks` використовуються для unknown/missing fields.
- Hard filters відсікають:
  - closed/expired grants;
  - country mismatch;
  - applicant type mismatch;
  - explicit restriction conflict;
  - training/tender/procurement/non-grant opportunities;
  - nonprofit-only grants для company clients.
- Keyword score використовує:
  - topic hits;
  - technology hits;
  - applicant type fit;
  - sector fit;
  - excluded topic penalty.
- Application history score:
  - дає boost за topic/text similarity;
  - дає boost за reusable materials;
  - не penalize-ить `lost`, `rejected`, `not_submitted`.

Stage 6 command:

- `docker compose exec app grant-tool match --top-n 5 --min-score 0.20`
- `docker compose exec app grant-tool match --client intelswift --top-n 10`

Поточний Docker smoke:

- evaluated 260 grant-client pairs;
- saved 3 strict shortlist matches;
- filtered 257;
- score range приблизно `0.2200-0.2273`.

Якість Stage 6 зараз: precision-oriented MVP. Він краще відсікає garbage, але recall буде обмежений до Stage 7 vector similarity.

Важливий принцип для наступних stages:

- Поточні grants у локальній DB є випадковим sample, а не ground truth dataset.
- Не підганяти matching logic під конкретні grants, які зараз лежать у DB.
- Додавати тільки generic rules, які мають сенс для багатьох джерел, клієнтів і майбутніх datasets.
- Source-specific або language-specific евристики мають бути конфігурованими rule sets з evidence, а не ad hoc logic.
- Stage 7 має будувати generic matching architecture, а не оптимізуватись під поточний scrape result.

## Dashboard

Перший web dashboard має включати:

- Grants list:
  - source filter
  - deadline filter
  - status filter
  - topic filter
  - applicant type filter
  - country filter
  - extraction confidence filter

- Client profiles:
  - список клієнтів
  - перегляд feature card
  - source YAML/CSV status

- Match view:
  - top grants per client
  - top clients per grant
  - score breakdown
  - LLM explanation
  - risks
  - manual review status

- Daily report:
  - нові гранти
  - оновлені гранти
  - кому можуть підійти
  - чому підходять
  - ризики
  - що треба перевірити вручну

## Automation

- Docker Compose startup має бути one-command:
  - `docker compose up --build` будує image і запускає весь local stack;
  - `docker compose up` запускає вже зібраний local stack;
  - одноразовий `migrate` service виконує `alembic upgrade head && grant-tool seed-sources`;
  - `app`, `worker` і `beat` стартують тільки після успішного `migrate`.
- `docker compose down` зупиняє services, але не видаляє database data.
- `docker compose down -v` видаляє PostgreSQL volume і використовується тільки для повного reset локальної бази.
- Scheduler запускає ingestion кожні 6-12 годин.
- Окремий daily job генерує report раз на день.
- Jobs мають бути idempotent.
- Помилки connector-ів мають логуватись без падіння всієї системи.

## Assumptions

- MVP запускається локально через Docker Compose.
- Docker Compose є основним способом запуску app під час розробки: `docker compose up --build` або `docker compose up`.
- У документації мають бути описані прямі Docker Compose команди для запуску, зупинки, logs і status.
- Authentication у першій версії не потрібна.
- Google Drive інтеграція відкладається до наступного етапу.
- Dashboard є internal tool, не polished public SaaS.
- LLM використовується для extraction і explanations.
- Deterministic filters залишаються основою shortlist.
- GrantForward, fundsforngos, OpportunityDesk та інші ширші джерела додаються після стабілізації MVP connector pattern.
