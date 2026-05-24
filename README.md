# AI Grant Matching Tool

AI Grant Matching Tool - це внутрішній web-інструмент для пошуку, нормалізації та matching грантових можливостей із профілями клієнтів або проєктів.

Мета системи - зменшити ручну роботу з дослідження грантів. Реалізований MVP збирає дані про гранти, зберігає raw snapshots, витягує структуровані поля, порівнює гранти з профілями клієнтів, враховує історію попередніх заявок, пояснює найкращі збіги і показує результат у внутрішньому dashboard.

Stage Search / Link Extraction завершений: configured connectors покривають усі implementable надані джерела, а restricted/deferred джерела мають documented reasons.

## Search Scope

Початковий MVP фокусувався на таких джерелах:

- EU Funding & Tenders Portal;
- Prostir grants;
- GURT grants;
- Diia Business finance programs.

Після завершеного Stage Search / Link Extraction робочі source connectors:

- EU Funding & Tenders Portal;
- Prostir grants;
- Diia Business finance programs;
- Chas Zmin;
- EUFundingPortal.eu;
- Hromady;
- NIPO;
- Grant Market;
- fundsforNGOs;
- Opportunity Desk;
- GrantForward.

GURT має локальний connector, але production validation блокується Cloudflare/human-check. GrantSense deferred, бо live validation не знайшла стабільний public direct opportunity feed.

Мапа grant fields і extraction: [docs/grant_fields_extraction_map.uk.svg](docs/grant_fields_extraction_map.uk.svg).

## Локальний Запуск

Звичайний локальний workflow запускається однією Docker Compose командою:

```bash
docker compose up --build
```

`docker compose down` зупиняє контейнери без видалення даних PostgreSQL.

`docker compose down -v` треба використовувати тільки тоді, коли потрібно видалити локальний PostgreSQL volume.

Детальні команди: [docs/start.md](docs/start.md).

Операційна шпаргалка: [docs/operations.md](docs/operations.md).

Після запуску dashboard доступний за адресами:

- `http://localhost:8000/`
- `http://localhost:8000/grants`
- `http://localhost:8000/clients`
- `http://localhost:8000/matches`
- `http://localhost:8000/report`

## Flow Системи

Система працює так:

1. Збирає raw grant data з configured sources.
2. Зберігає item-level search results у `discovered_grant_items`.
3. Зберігає raw snapshots для auditability.
4. Нормалізує grant fields: title, deadline, status, eligibility, applicant types, topics, funding amount, risks і source URL.
5. Завантажує client profiles і application history.
6. Match-ить grants із clients через hard filters, keyword scoring, vector similarity і application history boost.
7. Використовує LLM для enrichment неповних або нечітких полів і пояснення top matches.
8. Показує результат у dashboard report view.

Попередні заявки на схожі гранти вважаються позитивним relevance signal незалежно від outcome. `lost`, `rejected` або `not_submitted` не зменшують fit score, але можуть створити manual review notes.

## Tech Stack

- Backend: `FastAPI`
- API style: REST API first
- Dashboard: `Jinja2` + `HTMX`
- Database: `PostgreSQL` + `pgvector`
- ORM і migrations: `SQLAlchemy 2` + `Alembic`
- Jobs: CLI commands із `JobRun` audit records
- Broker/cache service у local stack: `Redis`
- AI provider: OpenAI
- Dependency management: Poetry
- Local runtime: Docker Compose
