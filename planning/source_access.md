# Аналіз доступу до джерел

## Мета

Перед Stage 2 і Stage 4 треба розуміти, які сайти можна читати через API або структурований feed, а де потрібен sitemap/HTML parsing.

Головне правило:

- спочатку використовуємо офіційний API або WordPress REST API;
- якщо API немає, використовуємо RSS;
- якщо RSS немає, використовуємо sitemap + HTML detail pages;
- browser automation залишаємо тільки для джерел, де HTML без JavaScript не дає потрібних даних.

## Підсумкова таблиця

| Джерело | Доступ | Рекомендована стратегія | Примітка |
|---|---|---|---|
| EU Funding & Tenders Portal | API | `api.tech.ec.europa.eu/search-api` з `apiKey=SEDIA` | Найкраще структуроване джерело для grants/calls/topics. |
| Prostir | RSS + HTML | RSS для списку, HTML detail для повного тексту | WordPress REST API не виглядає доступним. |
| GURT | HTML | HTML list + detail parsing | API/RSS не знайдено. |
| Grant Market | Sitemap + HTML | sitemap для URL, HTML detail parsing | Public API не знайдено. |
| Chas Zmin | WordPress REST API + RSS | WP REST API для posts, detail HTML/JSON для тексту | Добрий кандидат для structured ingestion. |
| GrantSense | Sitemap + HTML | sitemap/list page + HTML parsing | API/RSS не знайдено. |
| EUFundingPortal.eu | WordPress REST API + RSS | WP REST API або RSS | Це не офіційний EU Funding & Tenders Portal. |
| Diia Business | Sitemap + HTML | sitemap/list + SSR HTML parsing | Сайт має Angular SSR; public API швидко не знайдено. |
| fundsforNGOs | WordPress REST API | WP REST API | RSS/sitemap можуть бути заблоковані, але WP REST API працює. |
| Opportunity Desk | WordPress REST API + RSS | WP REST API | Добрий кандидат для structured ingestion. |
| GrantForward | HTML / possibly restricted | Defer або окремий connector після перевірки доступу | Public API/RSS не знайдено; може потребувати auth/subscription. |
| NIPO | WordPress REST API + RSS | WP REST API або RSS | Digest pages можна зберігати як raw HTML/JSON. |
| Hromady | WordPress REST API + RSS | WP REST API або RSS | Добрий кандидат для structured ingestion. |

## MVP-джерела

Для першої версії ingestion беремо 4 джерела:

- EU Funding & Tenders Portal
- Prostir
- GURT
- Diia Business

Стратегія по них:

### EU Funding & Tenders Portal

Використовуємо API, а не HTML scraping.

Реально доступні structured fields:

- identifier / topic id
- call identifier
- call title
- title
- status
- framework programme
- action type
- keywords
- description
- opening date
- deadline dates
- deadline model
- budget overview
- source topic URL / metadata URL

У database частину полів нормалізуємо в `grants`, а оригінальний вкладений JSON зберігаємо в `raw_grant_snapshots.raw_payload` і `grants.source_metadata`.

### Prostir

API не підтвердився, але є RSS.

Використовуємо:

- RSS/listing для discovery;
- detail HTML для full text, deadline, eligibility, amount, application instructions.

Більшість важливих fields будуть extraction from text, тому normalized поля мають бути optional.

### GURT

API/RSS не підтвердились.

Використовуємо:

- HTML listing для discovery;
- detail HTML для full text.

Це джерело треба робити обережно: polite requests, timeouts, невелика частота оновлення.

### Diia Business

Public API швидко не знайшовся.

Використовуємо:

- sitemap/list pages для discovery;
- server-rendered HTML detail pages для extraction;
- якщо HTML буде недостатньо, пізніше додамо browser-based inspection або окремий connector до внутрішнього API, якщо він буде стабільний.

## Вплив на Stage 2

У `Source` варто додати поля:

- `name`
- `slug`
- `base_url`
- `list_url`
- `api_url`
- `feed_url`
- `sitemap_url`
- `access_strategy`
- `requires_browser`
- `enabled`
- `rate_limit_seconds`
- `notes`

`access_strategy` має бути enum-like string:

- `api`
- `wp_rest`
- `rss`
- `sitemap_html`
- `html`
- `browser`
- `manual`

У `RawGrantSnapshot` треба зберігати і JSON, і HTML:

- `raw_payload` для API/WP REST/RSS parsed data;
- `raw_html` для detail pages;
- `raw_text` для cleaned text;
- `content_type`;
- `http_status`;
- `content_hash`;
- `metadata`.

Це дозволяє мати один database design для API-джерел і для HTML-джерел.

## Вплив на Stage 2.5

Перед реальним ingestion треба додати `JobRun` і seed для MVP sources.

`JobRun` потрібен для:

- історії запусків ingestion;
- статусу по кожному source;
- counters для processed/created/updated/skipped/failed records;
- збереження помилок connector-а без падіння всієї системи;
- dashboard visibility для crawler-а.

Seed sources має створити records для:

- `eu-funding`
- `prostir`
- `gurt`
- `diia-business`

Кожен seeded source має одразу містити:

- `base_url`
- `api_url`, `feed_url`, `list_url` або `sitemap_url`, якщо відомо;
- `access_strategy`;
- `rate_limit_seconds`;
- `requires_browser`;
- короткі `notes` про доступ.

## Вплив на Stage 3

Stage 3 треба починати не з конкретного source, а з connector framework.

Спільний framework має включати:

- `BaseConnector`;
- typed objects для fetched list item, fetched detail і normalized grant draft;
- shared `httpx` client з user-agent, timeout, retries і rate limit;
- content hashing для raw snapshots;
- ingestion service, який створює `JobRun`, зберігає raw snapshots і робить normalized grant upsert;
- fixture-based parser tests без обов'язкового live internet.

Порядок реалізації MVP connectors:

1. EU Funding & Tenders Portal через API.
2. Prostir через RSS discovery + HTML detail parsing.
3. Diia Business через sitemap/list + HTML detail parsing.
4. GURT через HTML list/detail parsing.

Причина такого порядку:

- EU Funding є найструктурованішим source і найкраще перевіряє database schema.
- Prostir дає перше українське джерело з RSS discovery.
- Diia Business додає business support/finance programmes, не тільки класичні grants.
- GURT менш структурований, тому його краще додавати після стабілізації parser framework.

## Вплив на поля grant

Не всі сайти дають однакову структуру, тому required fields мають бути мінімальними:

- `source_id`
- `source_url`
- `title`
- `status`
- `created_at`
- `updated_at`

Optional, але важливі для matching:

- `summary`
- `description_text`
- `deadline_at`
- `deadline_text`
- `program_name`
- `funder_name`
- `funding_amount_text`
- `eligibility_text`
- `applicant_types`
- `topics`
- `geography_text`
- `restrictions_text`
- `documents`
- `source_metadata`
- `extraction_metadata`

## Висновок

Так, EU Funding & Tenders Portal треба брати через API.

Для інших джерел підхід буде змішаний:

- WordPress REST API для сайтів, де він доступний;
- RSS там, де API немає, але feed є;
- sitemap + HTML parsing для решти;
- browser automation тільки якщо HTML/SSR не дасть достатньо даних.
