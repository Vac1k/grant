# План Для Search / Link Extraction

## Призначення Файлу

Цей файл містить тільки те, що ще треба реалізувати для великого Stage Search.

Правило роботи:

- коли пункт реалізовано і перевірено, він переноситься в `implemented_for_search.md`;
- якщо пункт тільки обговорений, він залишається тут;
- якщо пункт частково реалізований, тут лишається незакрита частина;
- Stage Search не закривається після однієї хвилі або одного підетапу.

## Великий Stage Search

Мета великого Stage Search - побудувати правильний, якісний і масштабований пошук грантів по всіх наданих сайтах, а не тільки по 4 MVP-джерелах.

Початкові вимоги:

1. Розширити логіку на всі надані сайти, а не лише на 4 MVP-джерела.
2. Пройтись по кожному сайту і знайти підхід до діставання якісних даних.
3. Зробити уніфікований підхід для діставання даних з кожного сайту.
4. Створити standardized initial table для збереження результатів пошуку перед raw details.
5. Покращити роль `raw_grant_snapshots`, не змішуючи raw audit data з бізнес-нормалізацією.
6. Зробити початкову логіку витягання всіх релевантних grant-like opportunities без обов'язкового active-only фільтра на рівні search.
7. Після початкового наповнення БД витягати тільки нові гранти, які з'явились, а не додавати повторно ті самі гранти.

## Коли Великий Stage Search Може Бути Завершений

Stage Search можна вважати завершеним тільки тоді, коли всі надані links із `docs/initial_sources.md` будуть закриті одним із двох способів:

1. Джерело реалізоване:
   - є source-specific connector;
   - є `discover`;
   - є `fetch_detail`;
   - є `normalize`;
   - item записується в `discovered_grant_items`;
   - grant записується або оновлюється в `grants`;
   - є automated tests;
   - є real website validation.

2. Джерело документовано відхилене:
   - немає public access;
   - потрібен login або paid access;
   - сайт блокує збір;
   - немає достатньо якісних даних;
   - немає стабільного search/list/detail механізму;
   - причина відхилення підтверджена реальною перевіркою.

Якщо хоча б один наданий link не реалізований, не протестований і не має documented rejection reason, Stage Search ще не завершений.

## Архітектурне Правило

Не робимо один універсальний scraper для всіх сайтів.

Правильний підхід:

```text
окремий source-specific connector для кожного сайту
  -> єдиний контракт discover/fetch_detail/normalize
  -> єдиний DTO DiscoveredGrantItemDraft
  -> єдина таблиця discovered_grant_items
  -> єдині правила incremental/backfill
  -> однаковий test і documentation стандарт
```

Стандартизуємо:

- output format;
- DTO;
- statuses;
- deduplication;
- `discovered_grant_items`;
- job counters;
- tests;
- documentation;
- real website validation format.

Не стандартизуємо як одну shared scraping logic:

- CSS selectors;
- API parameters;
- RSS parsing details;
- WP REST endpoint filters;
- sitemap filters;
- HTML fallback rules.

## Step 4: Реалізація Source-Specific Connectors

Ціль: реалізувати всі implementable джерела через однаковий контракт.

Кожен connector має мати:

```python
discover(limit, mode) -> list[DiscoveredGrantItemDraft]
fetch_detail(discovered_item) -> FetchedDetail
normalize(discovered_item, detail) -> NormalizedGrantDraft
```

Для кожного connector треба:

- додати class у `grant_tool/ingestion/connectors`;
- додати source seed;
- додати реєстрацію connector;
- додати fixtures або recorded samples;
- додати unit tests;
- додати ingestion tests;
- додати real website validation result;
- оновити документацію.

### Step 4.2: Хвиля 2

Ціль хвилі: закрити наступні джерела після першої production перевірки контракту на нових сайтах.

#### 4.2.1 NIPO

Hromady вже реалізовано у Step 4.1, тому в плані залишається NIPO.

#### 4.2.2 Grant Market

URL:

```text
https://grant.market/
```

Попередня стратегія:

- sitemap + HTML;
- public API не підтверджено.

Потрібно перевірити:

- sitemap opportunity URLs;
- list pages;
- stable detail pages;
- чи потрібен JavaScript;
- stable canonical URL.

Очікуваний key:

```text
canonical_url
fallback = item-level content_hash
```

#### 4.2.3 GrantSense

URL:

```text
https://grantsense.com.ua/
```

Попередня стратегія:

- sitemap/list + HTML;
- public API не підтверджено.

Потрібно перевірити:

- dedicated grants page;
- sitemap grant URLs;
- detail HTML quality;
- pagination;
- noise level.

Очікуваний key:

```text
canonical_url
fallback = normalized title + deadline або content_hash
```

#### 4.2.4 fundsforNGOs

URL:

```text
https://www2.fundsforngos.org/
```

Попередня стратегія:

- WordPress REST API;
- міжнародне джерело;
- потрібна перевірка rate limits і категорій.

Потрібно перевірити:

- WP REST availability;
- grants/funding category;
- rate limits;
- country/topic filters;
- detail content без subscription.

Очікуваний key:

```text
source_record_id = WP post id
fallback = canonical_url
```

### Step 4.3: Хвиля 3

Ціль хвилі: закрити ризиковані або шумні джерела.

#### 4.3.1 Opportunity Desk

URL:

```text
https://www.opportunitydesk.org/
```

Попередня стратегія:

- WordPress REST API або RSS;
- джерело широке і шумне;
- потрібна сильна фільтрація.

Потрібно перевірити:

- grants/funding categories/tags;
- noise level;
- stable WP post id;
- full detail content;
- topic filters.

Очікуваний key:

```text
source_record_id = WP post id
fallback = canonical_url або RSS GUID
```

#### 4.3.2 GrantForward

URL:

```text
https://www.grantforward.com/
```

Попередня стратегія:

- restricted HTML або possible paid access;
- ризиковане джерело.

Потрібно перевірити:

- public search/list page;
- detail pages без login;
- paid subscription requirement;
- чи дозволено збір;
- stable URL або id.

Очікуваний key:

```text
canonical_url, якщо public detail доступний
```

Якщо джерело потребує login або paid access, його треба позначити як rejected або deferred, але тільки після реальної перевірки.

## Step 5: Real Website Validation

Ціль: підтвердити, що connector працює не тільки на fixtures, а й на реальному сайті.

Для кожного джерела треба записати:

```text
source_slug:
tested_at:
tested_by:
real_url_used:
access_strategy:
discovered_count:
new_count:
known_count:
detail_fetched_count:
failed_count:
sample_titles:
sample_canonical_urls:
known_limitations:
decision:
```

Decision:

- `ready`;
- `ready_with_limitations`;
- `needs_fix`;
- `not_publicly_accessible`;
- `deferred`;
- `rejected`.

Deliverable цього step:

- real website validation record для кожного джерела;
- список fixes перед production use;
- documented rejection reasons для non-implementable джерел.

## Step 6: Логіка Інкрементального Збору Тільки Нових Грантів

Поточна базова логіка вже існує, але її треба підтвердити на всіх джерелах.

Правило:

- listing/search endpoint перечитується кожен run;
- новизна визначається по item-level key;
- known item не проходить detail-fetch у `incremental`;
- new item проходить detail-fetch, snapshot і normalization;
- `last_seen_at` оновлюється для known item.

Для кожного нового джерела треба перевірити:

- чи key стабільний між runs;
- чи pagination не змінює identity;
- чи tracking params не створюють дублікати;
- чи item-level hash не занадто нестабільний;
- чи new grant на старій list page буде знайдений.

Deliverable цього step:

- incremental tests для кожного connector;
- documented incremental key;
- documented duplicate risk.

## Step 7: Періодичне Оновлення Відомих Open Grants Після Extraction

Поточний `incremental` пропускає detail-fetch для known item. Це добре для нових грантів, але не бачить зміну дедлайну або умов на вже відомій сторінці.

Потрібне наступне покращення:

```text
refresh known open items every N days after status was determined by extraction
```

Попереднє правило:

- grants зі статусом `open` після extraction оновлювати кожні 7 днів;
- grants без deadline оновлювати кожні 14 днів;
- closed grants не оновлювати або оновлювати рідко;
- critical sources можуть мати коротший refresh interval.

Deliverable цього step:

- refresh policy;
- repository query для items due for refresh;
- job metadata для refresh run;
- tests.

## Step 8: Операційна Видимість

Потрібно додати спосіб бачити стан search.

Мінімально через SQL/CLI:

```sql
select source_slug, discovery_status, detail_fetch_status, count(*)
from discovered_grant_items
group by source_slug, discovery_status, detail_fetch_status
order by source_slug;
```

Бажано через dashboard або CLI report:

- discovered count by source;
- new count;
- known count;
- failed detail count;
- skipped known count;
- last seen date;
- sources with high failure rate;
- sources with high noise.

Deliverable цього step:

- CLI command або dashboard section;
- documented operator workflow.

## Step 9: Фінальна Документація І Закриття Stage Search

Перед закриттям Stage Search треба оновити:

- `implemented_for_search.md`;
- `plan_for_search.md`;
- `docs/initial_sources.md`;
- `docs/fields.md`;
- `docs/operations.md`;
- connector-specific notes;
- real website validation records.

Фінальна acceptance checklist:

- всі provided links закриті;
- всі implementable sources реалізовані;
- всі rejected/deferred sources мають причину;
- всі connectors мають tests;
- всі connectors перевірені на реальних сайтах;
- initial backfill працює;
- incremental new-only collection працює;
- refresh policy для known open grants після extraction визначена або реалізована;
- documentation відповідає фактичній реалізації.

## Підсумок

Це один великий Stage Search із кількома steps.

Хвилі по 4 джерела є тільки підпунктами Step 4, а не окремими stage-ами.

Stage Search не завершується після хвилі 1, хвилі 2 або реалізації MVP-джерел. Він завершується тільки після повного виконання початкових вимог: всі надані сайти проаналізовані, якісні джерела реалізовані, всі links протестовані на реальних сайтах, incremental new-only логіка підтверджена.
