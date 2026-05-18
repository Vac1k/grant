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

Ціль: створити структуру даних, у яку можна зберігати raw grants, normalized grants, clients, matches і reports.

Що зробити:

- Додати SQLAlchemy models для:
  - `Source`
  - `RawGrant`
  - `Grant`
  - `ClientProfile`
  - `ApplicationHistory`
  - `MatchRun`
  - `GrantClientMatch`
  - `Report`
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

## Stage 3: Client profiles і application history

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

## Stage 4: Ingestion connectors

Ціль: навчити систему збирати гранти з перших 4 джерел.

Що зробити:

- Створити загальний interface для connector-ів:
  - source name
  - fetch list
  - fetch detail, якщо потрібно
  - normalize basic fields
  - return raw payload/page + metadata
- Реалізувати connector для EU Funding & Tenders Portal:
  - спочатку перевірити API-style endpoint
  - якщо стабільного endpoint недостатньо, ізолювати fallback на structured extraction
- Реалізувати connector для Prostir:
  - перевірити RSS/структуровані сторінки
  - якщо потрібно, HTML parsing
- Реалізувати connector для GURT:
  - аналогічно: RSS/API first, HTML parsing fallback
- Реалізувати connector для Diia Business finance programs:
  - зібрати програми фінансування
  - зберігати source URL і raw payload/page
- Додати polite fetch behavior:
  - user-agent
  - timeout
  - retry з обмеженням
  - не робити агресивний scraping

Результат етапу:

- Система може зібрати список грантів із MVP-джерел.
- Raw data зберігається перед нормалізацією.
- Нові й оновлені гранти можна відрізняти через checksum.

## Stage 5: Normalization і feature extraction

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
