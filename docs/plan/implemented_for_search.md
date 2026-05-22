# Виконано Для Search / Link Extraction

## Призначення Файлу

Цей файл є єдиним місцем, куди переноситься все, що вже реалізовано для великого Stage Search.

Правило роботи з файлами:

- `plan_for_search.md` містить те, що ще треба зробити;
- `implemented_for_search.md` містить тільки те, що вже реалізовано і перевірено;
- після кожного наступного prompt-а виконаний пункт або підпункт переноситься з `plan_for_search.md` у цей файл;
- пункт не переноситься сюди, якщо він тільки обговорений, але ще не реалізований або не перевірений.

## Поточний Статус Великого Stage Search

Великий Stage Search ще не завершений.

Причина: зараз реалізована тільки базова інфраструктура search/link extraction і адаптація 4 MVP-джерел. Всі додаткові надані links ще не реалізовані як production-ready source-specific connectors і ще не перевірені на реальних сайтах.

Stage Search можна буде вважати завершеним тільки тоді, коли будуть виконані всі вимоги:

- логіка розширена на всі надані сайти;
- кожен сайт проаудитований;
- для кожного implementable сайту знайдено найкращий спосіб діставання якісних даних;
- створено і використано уніфікований контракт пошуку;
- standardized initial discovery table використовується перед `raw_grant_snapshots`;
- реалізовано початкове наповнення;
- реалізовано incremental логіку для нових грантів;
- всі implementable джерела протестовані локально;
- всі implementable джерела перевірені на реальних сайтах;
- non-implementable джерела мають задокументовану причину відхилення.

## Реалізовано: Базова Search Інфраструктура

### Стандартизований DTO

Реалізовано `DiscoveredGrantItemDraft`.

Він описує item-level результат пошуку перед повним завантаженням гранту.

Поля:

- `source_url`;
- `canonical_url`;
- `source_record_id`;
- `title_hint`;
- `summary_hint`;
- `published_at_hint`;
- `deadline_hint`;
- `listing_url`;
- `listing_position`;
- `content_hash`;
- `discovery_metadata`.

Це не повний grant record. Це standardized search result, який каже: система знайшла потенційний грант у list/API/RSS/sitemap/HTML.

### Режими Search

Реалізовано `DiscoveryMode`:

- `incremental`;
- `backfill`.

`incremental`:

- перечитує listing/RSS/API/search endpoint;
- формує candidate items;
- перевіряє, чи item уже існує в `discovered_grant_items`;
- для нового item робить detail-fetch;
- для відомого item пропускає detail-fetch.

`backfill`:

- перечитує listing/RSS/API/search endpoint;
- повторно робить detail-fetch навіть для вже відомого item.

### Статуси

Реалізовано `DiscoveryStatus`:

- `new`;
- `known`;
- `skipped`;
- `failed`.

Реалізовано `DetailFetchStatus`:

- `not_fetched`;
- `fetched`;
- `failed`;
- `skipped_known`.

### Стандартизована Початкова Таблиця

Реалізовано таблицю:

```text
discovered_grant_items
```

Це покращення ingestion flow перед `raw_grant_snapshots`.

Ролі таблиць тепер такі:

```text
discovered_grant_items
  -> стандартизований item-level результат пошуку

raw_grant_snapshots
  -> фактичний raw detail payload/html/text, який прийшов із сайту або API

grants
  -> нормалізований grant record для extraction, matching і dashboard
```

Важливо: `raw_grant_snapshots` не перетворюється на бізнес-таблицю і не має штучно заповнювати поля, яких сайт не дав. Якісна стандартизація починається в `discovered_grant_items`, а повна нормалізація живе в `grants`.

### Deduplication

Реалізовано пошук уже відомих item за пріоритетом:

1. `source_record_id`;
2. `canonical_url`;
3. `content_hash`.

Це потрібно, бо різні сайти мають різну якість структури:

- API може мати stable id;
- WordPress може мати post id;
- RSS може мати GUID;
- HTML може мати тільки URL;
- одна HTML-сторінка з багатьма грантами може потребувати item-level hash.

### Контракт Конектора

Реалізовано розділений контракт:

```python
discover(limit, mode) -> list[DiscoveredGrantItemDraft]
fetch_detail(discovered_item) -> FetchedDetail
normalize(discovered_item, detail) -> NormalizedGrantDraft
```

Відповідальність:

- `discover` знаходить потенційні гранти;
- `fetch_detail` завантажує повний detail payload або HTML;
- `normalize` мапить detail у стандартну структуру гранту.

### Ingestion Flow

Реалізований flow:

```text
Source
  -> Connector.discover(limit, mode)
  -> DiscoveredGrantItemDraft
  -> discovered_grant_items
  -> якщо item новий або mode=backfill:
       Connector.fetch_detail(item)
       Connector.normalize(item, detail)
       FeatureExtractionService
       raw_grant_snapshots
       grants
  -> якщо item відомий і mode=incremental:
       detail-fetch пропускається
```

Ключове правило вже реалізоване: listing/search endpoint читається кожного разу. Пропуск застосовується тільки до вже відомого item-level гранту, а не до сторінки списку.

## Реалізовано: MVP-Джерела

### EU Funding & Tenders Portal

Статус: реалізовано локально.

Поточний search strategy:

- використовується EU Funding & Tenders Search API;
- API item мапиться у `DiscoveredGrantItemDraft`;
- `source_record_id` береться з API id або identifier;
- `canonical_url` будується з URL opportunity;
- raw API item зберігається в `discovery_metadata`;
- detail-fetch для цього джерела використовує API item як detail payload.

Ще потрібно для фінального Stage Search:

- real website validation;
- підтвердити, що API стабільно повертає актуальні opportunities;
- підтвердити, що active/closed статус і deadline витягуються достатньо якісно.

### Prostir

Статус: реалізовано локально.

Поточний search strategy:

- використовується RSS feed;
- якщо RSS не дає items, можливий fallback на HTML list;
- `guid` або link використовується як `source_record_id`;
- detail HTML завантажується окремо;
- deadline, documents і full text витягуються з detail HTML.

Ще потрібно для фінального Stage Search:

- real website validation;
- підтвердити, що RSS стабільний;
- підтвердити, що detail pages дають достатньо якісний текст.

### Diia Business

Статус: реалізовано локально.

Поточний search strategy:

- використовується public frontend finance API;
- list endpoint дає finance services;
- service id або slug використовується як item key;
- detail endpoint завантажує service detail payload;
- sitemap/HTML логіка лишається fallback.

Ще потрібно для фінального Stage Search:

- real website validation;
- підтвердити стабільність frontend API;
- підтвердити, що finance services релевантні до grant/business support use case.

### GURT

Статус: реалізовано локально.

Поточний search strategy:

- використовується HTML list page;
- links із `/news/grants/` мапляться у `DiscoveredGrantItemDraft`;
- canonical detail URL використовується як key;
- detail HTML парситься окремо.

Ще потрібно для фінального Stage Search:

- real website validation;
- підтвердити, що HTML selectors не зламались;
- підтвердити, що list page стабільно дає прямі detail links.

## Реалізовано: CLI

Додано режим:

```bash
grant-tool ingest --mode incremental
grant-tool ingest --mode backfill
```

Приклад:

```bash
docker compose exec app grant-tool ingest --all --limit 20 --mode incremental
```

## Реалізовано: Тести

Перевірено локальними automated tests:

- repository flow для `discovered_grant_items`;
- ingestion flow;
- incremental skip для відомих item;
- адаптація MVP-конекторів;
- повний локальний test suite через `unittest`.

Останній зафіксований результат:

```text
Ran 46 tests
OK
```

## Ще Не Перенесено В Implemented

Ці частини залишаються в `plan_for_search.md`, бо вони ще не завершені:

- аудит усіх наданих сайтів;
- реалізація нових source-specific connectors;
- хвилі реалізації по 4 джерела;
- real website validation для всіх джерел;
- логіка active-only або broad collection для кожного нового сайту;
- регулярне оновлення відомих active grant details;
- discovery dashboard або CLI report;
- фінальне закриття Stage Search.
