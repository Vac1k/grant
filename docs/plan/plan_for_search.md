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
6. Зробити початкову логіку витягання всіх активних грантів або всіх релевантних грантів, якщо active-only ненадійний.
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

## Step 1: Аудит Усіх Наданих Джерел

Ціль: пройтись по кожному сайту і визначити найкращий спосіб діставання якісних даних.

Для кожного джерела треба заповнити:

```text
source_name:
source_slug:
base_url:
candidate_urls:
access_strategy:
search_url:
detail_strategy:
pagination_strategy:
stable_id_strategy:
incremental_key:
active_only_possible:
data_quality:
noise_level:
implementation_complexity:
risk_level:
recommendation:
```

Що треба перевірити:

- чи є API;
- чи є WordPress REST API;
- чи є RSS;
- чи є sitemap;
- чи є стабільна HTML list page;
- чи є стабільна detail page;
- чи можна отримати title і URL без browser automation;
- чи є stable ID;
- чи є pagination;
- чи можна обмежити тільки гранти;
- чи можна визначити active/closed на list рівні;
- чи detail page має дедлайн, умови, funder, amount, geography, documents;
- чи сайт не потребує login або paid subscription.

Deliverable цього step:

- audit matrix для всіх джерел;
- recommendation для кожного джерела: `implement`, `implement_with_limitations`, `defer`, `reject`;
- список джерел для реалізації хвилями.

## Step 2: Уточнення Standardized Initial Table

Ціль: зробити standardized initial table для первинного search result, щоб система мала однакову точку входу для всіх сайтів.

Поточна реалізована таблиця:

```text
discovered_grant_items
```

Що треба ще уточнити:

- які поля є обов'язковими для всіх джерел;
- які поля можуть бути null;
- як позначати неповні дані;
- як зберігати source-specific metadata;
- як відрізняти low quality item від failed item;
- чи потрібне поле `quality_score`;
- чи потрібне поле `is_probably_grant`;
- чи потрібне поле `active_hint`;
- чи потрібне поле `requires_manual_review`.

Важливе рішення:

`raw_grant_snapshots` не має бути таблицею, де всі бізнес-поля штучно заповнені. Вона має залишатися audit table для raw payload/html/text. Покращення полягає в тому, що перед нею є стандартизована search table `discovered_grant_items`, а після неї є нормалізована бізнес-таблиця `grants`.

Deliverable цього step:

- фінальний schema description для `discovered_grant_items`;
- правила, які поля мають бути filled, які можуть бути null, і як це пояснюється через status/metadata;
- правила quality flags для junior developer.

## Step 3: Логіка Початкового Наповнення

Ціль: зробити початкову логіку збору грантів для кожного джерела.

Основне правило:

```text
якщо active-only надійний -> збираємо active grants
якщо active-only ненадійний -> збираємо всі релевантні grant-like opportunities
```

Чому не завжди active-only:

- не всі сайти показують статус у list;
- deadline часто є тільки на detail page;
- деякі гранти мають rolling deadline;
- деякі сайти не мають structured date;
- aggressive active-only filter може пропустити корисні гранти.

Для кожного джерела треба визначити:

- backfill depth;
- pagination limit;
- category/tag filters;
- date filters;
- country/topic filters;
- whether old/closed grants should be stored;
- max requests per run;
- rate limit.

Deliverable цього step:

- backfill rule для кожного джерела;
- active/all decision для кожного джерела;
- safe request limits;
- documented reason for the chosen strategy.

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

### Step 4.1: Хвиля 1

Ціль хвилі: додати перші 4 нові джерела, які мають найкраще співвідношення користі до складності.

#### 4.1.1 Chas Zmin

URL:

```text
https://chaszmin.com.ua/
```

Попередня стратегія:

- WordPress REST API або RSS;
- WP REST як primary, якщо стабільний;
- RSS як fallback;
- HTML detail або WP content для повного тексту.

Потрібно перевірити:

- `/wp-json/wp/v2/posts`;
- categories/tags для грантів;
- title/link/excerpt/date/content в API;
- stable WP post id;
- якість detail content.

Очікуваний key:

```text
source_record_id = WP post id
fallback = canonical_url
```

#### 4.1.2 EUFundingPortal.eu

URL:

```text
https://eufundingportal.eu/
```

Попередня стратегія:

- WordPress REST API або RSS;
- агрегатор, не заміна official EU Funding source.

Потрібно перевірити:

- WP REST availability;
- RSS availability;
- category/tag filters;
- чи posts дійсно містять grant opportunities;
- duplicate risk with official EU source.

Очікуваний key:

```text
source_record_id = WP post id
fallback = canonical_url або RSS GUID
```

#### 4.1.3 GURT Grant Competitions

URL:

```text
https://grants.gurt.org.ua/
```

Попередня стратегія:

- HTML list + HTML detail;
- окрема платформа конкурсів ГУРТ;
- не замінює `https://www.gurt.org.ua/news/grants/`.

Потрібно перевірити:

- stable list page;
- direct detail URLs;
- pagination;
- active/closed indication;
- deadline, eligibility, funder, documents на detail page.

Очікуваний key:

```text
canonical_url
fallback = normalized title + deadline або item-level content_hash
```

#### 4.1.4 Hromady Або NIPO

Primary candidate:

```text
https://hromady.org/
```

Backup candidate:

```text
https://nipo.gov.ua/
```

Рішення між Hromady і NIPO приймається після audit якості категорій.

Hromady попередня стратегія:

- WordPress REST API або RSS;
- джерело для громад і локального розвитку;
- якість залежить від категорій.

NIPO попередня стратегія:

- WordPress REST API або RSS;
- може бути digest source, а не direct grant source.

Очікуваний key:

```text
source_record_id = WP post id
fallback = canonical_url
```

Важливо: якщо у хвилі 1 обрано Hromady, NIPO все одно залишається в плані. Якщо обрано NIPO, Hromady все одно залишається в плані. Stage Search завершується тільки після закриття обох.

### Step 4.2: Хвиля 2

Ціль хвилі: закрити наступні джерела після першої production перевірки контракту на нових сайтах.

#### 4.2.1 NIPO Або Hromady

Це джерело, яке не було взято в хвилю 1.

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

## Step 7: Періодичне Оновлення Відомих Active Grants

Поточний `incremental` пропускає detail-fetch для known item. Це добре для нових грантів, але не бачить зміну дедлайну або умов на вже відомій сторінці.

Потрібне наступне покращення:

```text
refresh known active items every N days
```

Попереднє правило:

- active grants оновлювати кожні 7 днів;
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
- refresh policy для known active grants визначена або реалізована;
- documentation відповідає фактичній реалізації.

## Підсумок

Це один великий Stage Search із кількома steps.

Хвилі по 4 джерела є тільки підпунктами Step 4, а не окремими stage-ами.

Stage Search не завершується після хвилі 1, хвилі 2 або реалізації MVP-джерел. Він завершується тільки після повного виконання початкових вимог: всі надані сайти проаналізовані, якісні джерела реалізовані, всі links протестовані на реальних сайтах, incremental new-only логіка підтверджена.
