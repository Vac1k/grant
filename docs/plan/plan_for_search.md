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
   - для кожного implementable джерела, крім `gurt`, у БД додано мінімум 10 якісних grant records;
   - 10 records перевірені як релевантні grant-like opportunities, а не просто будь-які новини або broad finance pages;
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

Окреме правило якості: Stage Search не можна завершити тільки тому, що connector повернув один sample item. Для кожного implementable джерела потрібно виконати production backfill/validation і отримати мінімум 10 якісних grants у `grants`. Виняток: `gurt`, бо правильний URL блокується Cloudflare/human-check і вже має documented access limitation. Deferred/restricted джерела не рахуються як implementable, доки не з'явиться стабільний public access path.

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

## Step 9: Production Backfill І Quality Gate На 10 Grants Для Кожного Джерела

Step 5 перевірив, що connectors можуть дістати 1 live sample. Цього недостатньо для завершення Stage Search.

Потрібно виконати production-oriented run, який доводить, що кожне implementable джерело реально дає достатню кількість якісних grant records.

Правило:

- для кожного implementable configured source, крім `gurt`, у таблиці `grants` має бути мінімум 10 якісних records;
- `gurt` не блокує completion тільки через Cloudflare/human-check, якщо documented access limitation лишається актуальним;
- `grantsense` і `grantforward` не входять у count, доки вони documented deferred/restricted без stable connector;
- якщо deferred/restricted джерело пізніше стане implementable, воно теж має пройти правило 10 якісних grants;
- записи мають бути результатом реального connector run, а не тільки fixture test;
- quality має перевірятись через title/source_url/status/deadline/funding text/manual review flags;
- broad/news/digest records можна зберігати, але вони не рахуються у 10 якісних, якщо не є grant-like opportunity.

Мінімальний expected source set для цього step:

- `eu-funding`;
- `prostir`;
- `diia-business`;
- `chas-zmin`;
- `eufundingportal-eu`;
- `hromady`;
- `nipo`;
- `grant-market`;
- `fundsforngos`;
- `opportunitydesk`.

Потрібно для кожного source зафіксувати:

- connector run command;
- кількість discovered items;
- кількість created/updated grants;
- кількість records у `grants` після run;
- скільки з них quality-approved;
- приклади 10 records або query result із title/source_url/status/deadline;
- причини, чому records вважаються якісними;
- rejected/noisy records, якщо вони були.

Приклад SQL для перевірки кількості:

```sql
select s.slug, count(*) as grants_count
from grants g
join sources s on s.id = g.source_id
where s.slug != 'gurt'
group by s.slug
order by s.slug;
```

Приклад SQL для ручного quality review:

```sql
select
  s.slug,
  g.title,
  g.status,
  g.deadline,
  g.funding_amount_text,
  g.source_url,
  g.needs_manual_review
from grants g
join sources s on s.id = g.source_id
where s.slug = '<source-slug>'
order by g.created_at desc
limit 20;
```

Deliverable цього step:

- live backfill виконаний для кожного implementable source;
- для кожного source є мінімум 10 quality-approved grants;
- `gurt` має актуальну documented Cloudflare limitation;
- `grantsense` і `grantforward` лишаються documented deferred/restricted або переводяться в implementable і теж проходять 10-grant gate;
- результати перенесені в `implemented_for_search.md`;
- Stage Search все ще не закривається, якщо хоча б один implementable source має менше 10 quality-approved grants.

## Step 10: Фінальна Документація І Закриття Stage Search

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
- кожне implementable джерело, крім `gurt`, має мінімум 10 quality-approved grants у `grants`;
- `gurt` має актуальне documented Cloudflare/human-check limitation без bypass;
- initial backfill працює;
- incremental new-only collection працює;
- refresh policy для known open grants після extraction визначена або реалізована;
- documentation відповідає фактичній реалізації.

## Підсумок

Це один великий Stage Search із кількома steps.

Хвилі реалізації джерел уже перенесені в `implemented_for_search.md`; вони не є окремими stage-ами.

Stage Search не завершується після реалізації MVP-джерел або перевірки конекторів на реальних сайтах. Він завершується тільки після повного виконання початкових вимог: всі надані сайти проаналізовані, якісні джерела реалізовані або documented deferred/restricted, incremental new-only логіка підтверджена, refresh policy визначена, операційна видимість search додана, і кожне implementable джерело, крім `gurt`, має мінімум 10 quality-approved grants у `grants`.
