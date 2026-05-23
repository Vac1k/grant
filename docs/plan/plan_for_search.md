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

Хвилі реалізації джерел уже перенесені в `implemented_for_search.md`; вони не є окремими stage-ами.

Stage Search не завершується після реалізації MVP-джерел або перевірки конекторів на реальних сайтах. Він завершується тільки після повного виконання початкових вимог: всі надані сайти проаналізовані, якісні джерела реалізовані або documented deferred/restricted, incremental new-only логіка підтверджена, refresh policy визначена, і операційна видимість search додана.
