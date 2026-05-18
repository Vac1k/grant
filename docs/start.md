# Start Guide

Цей документ описує базові команди для локального запуску AI Grant Matching Tool.

## Основний підхід

Основний спосіб запуску проєкту — через Docker Compose.

Це важливо, бо app залежить не тільки від Python/FastAPI, а й від:

- PostgreSQL з `pgvector`
- Redis
- Celery worker у наступних етапах
- Celery scheduler у наступних етапах

Тому стандартний запуск має бути через одну Docker Compose команду, а не через окремий запуск кожного сервісу.

## Перший запуск

Перейти в директорію проєкту:

```bash
cd /Users/vac1k/Projects/ai_replace_grandwriters/grant
```

Створити локальний `.env` файл:

```bash
cp .env.example .env
```

Запустити app, database і Redis:

```bash
docker compose up --build
```

Після запуску app буде доступний тут:

- app: `http://localhost:8000`
- health: `http://localhost:8000/api/v1/health`
- OpenAPI docs: `http://localhost:8000/docs`

## Звичайний щоденний запуск

Якщо `.env` вже створений:

```bash
docker compose up
```

Якщо змінювались dependencies або Dockerfile:

```bash
docker compose up --build
```

## Запуск з worker і scheduler

Worker і scheduler поки підготовлені для наступних етапів.

Коли вони будуть потрібні:

```bash
docker compose --profile worker --profile scheduler up --build
```

Ця команда запускає:

- `app`
- `db`
- `redis`
- `worker`
- `beat`

## Зупинка

Зупинити services:

```bash
docker compose down
```

Зупинити services і видалити volumes з database data:

```bash
docker compose down -v
```

Команду `docker compose down -v` використовувати обережно, бо вона видаляє локальні дані PostgreSQL.

## Logs

Дивитись logs усіх services:

```bash
docker compose logs -f
```

Дивитись logs тільки app:

```bash
docker compose logs -f app
```

Дивитись logs database:

```bash
docker compose logs -f db
```

Дивитись logs Redis:

```bash
docker compose logs -f redis
```

## Status

Подивитись статус services:

```bash
docker compose ps
```

## Health check

Перевірити, що API працює:

```bash
curl http://localhost:8000/api/v1/health
```

Очікувана відповідь:

```json
{"status":"ok","service":"AI Grant Matching Tool","environment":"local"}
```

## OpenAPI docs

FastAPI автоматично генерує API документацію.

Відкрити в браузері:

```text
http://localhost:8000/docs
```

## Локальний запуск без Docker

Цей спосіб не є основним.

Його можна використовувати тільки для точкового debugging:

```bash
poetry install
poetry run uvicorn grant_tool.main:app --reload
```

Для нормальної розробки використовувати Docker Compose.

## Поточні services

`app`:

- FastAPI application
- port `8000`
- команда всередині container: `uvicorn grant_tool.main:app --host 0.0.0.0 --port 8000 --reload`

`db`:

- PostgreSQL 16
- image: `pgvector/pgvector:pg16`
- database: `grant`
- user: `grant`
- password: `grant`
- port `5432`

`redis`:

- Redis 7
- port `6379`
- broker для Celery

`worker`:

- Celery worker
- запускається тільки з profile `worker`

`beat`:

- Celery scheduler
- запускається тільки з profile `scheduler`

## Основні правила

- Не запускати app вручну як основний workflow.
- Не запускати PostgreSQL або Redis окремо, якщо працюємо над MVP.
- Нові runtime services треба додавати в `docker-compose.yml`.
- README має бути коротким, а детальні команди мають жити в `docs/start.md`.
- `.env` використовується Docker Compose для environment variables, але не має копіюватись у Docker image або монтуватись у app container.
