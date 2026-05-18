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
  - Docker Compose для app, database, worker і scheduler
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

- Для EU Funding & Tenders Portal спочатку перевірити можливість роботи через офіційний/API-style доступ.
- Якщо стабільного публічного API недостатньо, ізолювати EU connector і зробити fallback на контрольоване structured extraction зі сторінок пошуку/details.
- Для Prostir, GURT і Diia:
  - спочатку шукати RSS/API/структуровані endpoints
  - якщо їх немає, використовувати polite HTML parsing із source-specific selectors
- Кожен fetch має зберігати raw data перед нормалізацією.
- Дедуплікація через source URL, source ID і checksum.
- Повторний запуск ingestion не має створювати дублікати.

## Feature Extraction

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

## Matching

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

- Scheduler запускає ingestion кожні 6-12 годин.
- Окремий daily job генерує report раз на день.
- Jobs мають бути idempotent.
- Помилки connector-ів мають логуватись без падіння всієї системи.

## Assumptions

- MVP запускається локально через Docker Compose.
- Docker Compose є основним способом запуску app під час розробки: `docker compose up --build`.
- У документації мають бути описані прямі Docker Compose команди для запуску, зупинки, logs і status.
- Authentication у першій версії не потрібна.
- Google Drive інтеграція відкладається до наступного етапу.
- Dashboard є internal tool, не polished public SaaS.
- LLM використовується для extraction і explanations.
- Deterministic filters залишаються основою shortlist.
- GrantForward, fundsforngos, OpportunityDesk та інші ширші джерела додаються після стабілізації MVP connector pattern.
