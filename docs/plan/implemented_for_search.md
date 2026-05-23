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

Причина: зараз реалізована базова інфраструктура search/link extraction, адаптація 4 MVP-джерел, виконаний аудит усіх наданих джерел, уточнений контракт standardized initial table, зафіксовані правила початкового наповнення, реалізовано Step 4.1, Step 4.2 і Step 4.3 для нових джерел, закрито Step 5 real website validation, підтверджено Step 6 incremental behavior для всіх configured connectors, реалізовано Step 7 refresh policy для відомих open/unknown grants, а також додано Step 8 CLI operational visibility. Stage Search ще не завершений, бо попереду залишаються production backfill/quality gate на 10 grants для кожного implementable джерела і фінальне закриття документації.

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
- кожне implementable джерело, крім `gurt`, має мінімум 10 quality-approved grants у `grants`;
- `gurt` має актуальну documented Cloudflare/human-check limitation без bypass;
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

## Реалізовано: Step 1 - Аудит Усіх Наданих Джерел

Статус: виконано.

Дата audit: `2026-05-23`.

Мета Step 1 була пройтись по кожному сайту з `docs/initial_sources.md` і визначити найкращий спосіб діставання якісних даних.

Важливо: це був endpoint/access audit, а не реалізація нових production connectors. Для кожного джерела перевірено доступні API/RSS/sitemap/list endpoints і визначено рекомендований підхід.

### Summary Audit Matrix

| Джерело | Slug | Live evidence | Рекомендована стратегія | Incremental key | Якість | Ризик | Рішення |
|---|---|---|---|---|---|---|---|
| EU Funding & Tenders Portal | `eu-funding` | Portal `200`; Search API endpoint відповідає `405` на GET, бо поточний connector має використовувати POST. | API-first через EU Search API. | `source_record_id` з API id/reference. | Висока | Низький/середній | `implement`, вже є MVP connector, потрібна real POST validation. |
| Prostir | `prostir` | RSS `200`; WP grants endpoint redirects/returns HTML, тому RSS лишається кращим. | RSS discovery + HTML detail. | RSS GUID або canonical URL. | Середня/висока | Низький | `implement`, вже є MVP connector. |
| Diia Business | `diia-business` | Frontend finance API `200`. | Public frontend API list + API detail; sitemap/HTML fallback. | service id або slug. | Висока | Середній, бо frontend API може змінитись. | `implement`, вже є MVP connector. |
| GURT | `gurt` | Правильний URL `https://gurt.org.ua/news/grants/`; HTML/RSS зараз повертають `403` через Cloudflare/human-check. | HTML list + HTML detail тільки якщо є дозволений доступ або альтернативний public endpoint. | canonical URL. | Середня | Високий через Cloudflare/human-check. | `implemented_locally_not_production_validated`, connector є, потрібен легальний спосіб live access. |
| GURT grant competitions | `gurt-grant-competitions` | Уточнено користувачем: це не окремий правильний source для поточної задачі; правильний link - `https://gurt.org.ua/news/grants/`. | Не реалізовувати як окреме джерело. | n/a | n/a | n/a | `removed_as_wrong_duplicate_source`. |
| Grant Market | `grant-market` | `sitemap.xml` `200`, багато `/opp/...` URLs; WP REST/RSS `404`. | Sitemap discovery + HTML detail for `/opp/` URLs. | canonical URL. | Середня/висока | Середній | `implement`. |
| Chas Zmin | `chas-zmin` | WP REST `200`, RSS `200`, WP search for `грант` повертає релевантні grant posts. | WP REST primary, RSS fallback. | WP post id, fallback canonical URL. | Висока | Низький | `implement`, перша хвиля. |
| GrantSense | `grantsense` | Sitemap `200`; WP REST/RSS `404`; sitemap має service/blog/grant category pages, але не очевидний active opportunities feed. | Sitemap/HTML only; потрібна фільтрація і перевірка, чи це source opportunities, а не service/content marketing. | canonical URL або content hash. | Низька/середня | Середній/високий через noise. | `defer`, реалізувати тільки якщо підтвердиться корисність як grant opportunity source. |
| EUFundingPortal.eu | `eufundingportal-eu` | WP REST `200`, RSS `200`, sitemap `200`; categories містять funding/grants programmes. | WP REST primary, RSS fallback; category filters. | WP post id, fallback canonical URL/RSS GUID. | Середня/висока | Середній через aggregator/paywall/membership risk. | `implement_with_limitations`. |
| fundsforNGOs | `fundsforngos` | WP REST `200`, RSS `200`, search for `grant` повертає direct grant posts. | WP REST primary with category/topic/country filters. | WP post id, fallback canonical URL. | Висока, але широка | Середній через rate limits/noise. | `implement_with_filters`. |
| Opportunity Desk | `opportunitydesk` | WP REST `200`, RSS `200`, sitemap `200`, search for `grant` повертає direct grant posts. | WP REST primary, RSS fallback, strong filters. | WP post id, fallback canonical URL/RSS GUID. | Середня | Середній/високий через noisy opportunities. | `implement_with_filters`. |
| GrantForward | `grantforward` | `/search` `200`, але WP REST/RSS/sitemap `404`; search page heavy HTML/JS і може бути account/institution product. | Restricted HTML/search page only; public ingestion uncertain. | canonical URL only if public detail URLs доступні. | Невідома | Високий | `defer_or_reject_after_detail_access_check`. |
| NIPO | `nipo` | WP REST `200`, RSS `200`, search for `грант` повертає grant-related posts. | WP REST primary, RSS fallback; likely digest/news source. | WP post id, fallback canonical URL. | Середня | Середній через digest/noise. | `implement_with_limitations`. |
| Hromady | `hromady` | WP REST `200`, RSS `200`, search for `грант` повертає релевантні posts. | WP REST primary, RSS fallback; category/search filters. | WP post id, fallback canonical URL. | Середня/висока | Низький/середній | `implement`, перша хвиля або backup with NIPO. |

### Endpoint Evidence

Це короткий evidence log з live endpoint checks.

| Джерело | Перевірені endpoints | Результат |
|---|---|---|
| EU Funding & Tenders Portal | `https://ec.europa.eu/info/funding-tenders/opportunities/portal/`; `https://api.tech.ec.europa.eu/search-api/prod/rest/search?...` | Portal `200`; API GET `405`, очікувано для connector-а, який використовує POST. |
| Prostir | `https://www.prostir.ua/category/grants/feed/`; `https://www.prostir.ua/wp-json/wp/v2/grants?per_page=1` | RSS `200`; WP endpoint не є кращим primary, бо повертає HTML/redirect. |
| Diia Business | `https://api.business.diia.gov.ua/api/front/finance?take=1&skip=0` | API `200 application/json`. |
| GURT | `https://gurt.org.ua/news/grants/`; `https://gurt.org.ua/news/grants/rss/` | `403 text/html`; користувач підтвердив Cloudflare/human-check. |
| GURT grant competitions | `https://grants.gurt.org.ua/` | Прибрано як окреме джерело після уточнення користувача; правильний source - `gurt`. |
| Grant Market | `https://grant.market/sitemap.xml`; `https://grant.market/wp-json/`; `https://grant.market/feed/` | Sitemap `200`; WP/RSS `404`; sitemap має багато `/opp/` URLs. |
| Chas Zmin | `https://chaszmin.com.ua/wp-json/`; `.../wp/v2/posts`; `.../feed/`; WP search `грант` | WP REST `200`; RSS `200`; search returns grant posts. |
| GrantSense | `https://www.grantsense.com.ua/sitemap.xml`; `.../wp-json/`; `.../feed/` | Sitemap `200`; WP/RSS `404`; source likely HTML/sitemap with high noise. |
| EUFundingPortal.eu | `https://eufundingportal.eu/wp-json/`; `.../feed/`; `.../sitemap.xml`; WP categories | WP REST/RSS/sitemap `200`; categories contain grants/funding programmes. |
| fundsforNGOs | `https://www2.fundsforngos.org/wp-json/wp/v2/posts?per_page=1`; `.../feed/`; search `grant` | WP REST `200`; RSS `200`; search returns grant posts. |
| Opportunity Desk | `https://opportunitydesk.org/wp-json/wp/v2/posts?per_page=1`; `.../feed/`; `.../sitemap.xml`; search `grant` | WP REST/RSS/sitemap `200`; search returns grant posts. |
| GrantForward | `https://www.grantforward.com/search`; `.../wp-json/`; `.../feed/`; `.../sitemap.xml` | Search page `200`; WP/RSS/sitemap `404`; high restriction/account risk. |
| NIPO | `https://nipo.gov.ua/wp-json/wp/v2/posts?per_page=1`; `.../feed/`; search `грант` | WP REST `200`; RSS `200`; search returns grant-related posts. |
| Hromady | `https://hromady.org/wp-json/wp/v2/posts?per_page=1`; `.../feed/`; search `грант` | WP REST `200`; RSS `200`; search returns grant posts. |

### Рекомендований Порядок Після Audit

Step 1 підтвердив два сильні кандидати з початкової хвилі і виявив один ризикований слот:

1. `Chas Zmin` - найкращий перший кандидат: WP REST/RSS працюють, search returns grant posts.
2. `EUFundingPortal.eu` - WP REST/RSS працюють, але треба врахувати aggregator/paywall risk.
3. `Hromady` або `NIPO` - обидва мають WP REST/RSS; Hromady виглядає більш прямим grant source, NIPO більше схожий на news/digest source.
4. `GURT` потребує окремого production access рішення, бо правильний URL блокується Cloudflare/human-check.

Якщо для `GURT` не буде легального способу automated access, його не можна позначати production validated. Якщо потрібен четвертий fully validated source у хвилі 1, найкращий кандидат на заміну слота - `Grant Market`, бо sitemap має багато `/opp/` URLs і виглядає технічно доступнішим. Таку заміну треба погодити окремо.

### Ризики, Які Виявив Audit

- `GURT`: правильний URL блокується Cloudflare/human-check; не можна робити bypass без дозволеного підходу.
- `GrantForward`: search page доступна, але немає простого public API/RSS/sitemap; високий ризик login/institution restriction.
- `GrantSense`: sitemap доступний, але сайт більше схожий на service/content site, а не стабільний feed грантових можливостей.
- `EUFundingPortal.eu`: корисний aggregator, але треба перевірити, скільки detail content доступно без membership.
- `fundsforNGOs` і `OpportunityDesk`: багато релевантних posts, але потрібні filters через noise і міжнародну широту.

## Реалізовано: Step 2 - Уточнення Standardized Initial Table

Статус: виконано.

Дата рішення: `2026-05-23`.

Мета Step 2 була уточнити, які саме поля має заповнювати search/link extraction stage, які поля можуть бути `null`, як позначати якість item і як відрізняти неповний search result від справжньої помилки.

Важливе рішення: на цьому step не додаємо нову міграцію і не міняємо структуру БД. Поточна таблиця `discovered_grant_items` достатня для v1, а quality/decision hints зберігаються в `discovery_metadata`. Якщо після реальних ingestion runs буде потрібно часто фільтрувати по якості на рівні SQL, тоді окремим майбутнім schema step можна винести частину metadata у колонки.

### Фінальна Роль Таблиці

`discovered_grant_items` - це standardized initial table для результату пошуку.

Вона зберігає не повний грант, а candidate item, який connector знайшов у API, RSS, sitemap, HTML list або search page.

Правильний pipeline:

```text
source connector
  -> discover()
  -> discovered_grant_items
  -> fetch_detail()
  -> raw_grant_snapshots
  -> normalize()
  -> grants
```

`raw_grant_snapshots` лишається audit table для raw payload/html/text. Її не треба змушувати мати всі бізнес-поля. Повна бізнес-нормалізація живе в `grants`.

### Поля Таблиці І Правила Заповнення

| Поле | Обов'язковість | Правило |
|---|---|---|
| `source_id` | required | Внутрішній id джерела з таблиці `sources`. |
| `source_slug` | required | Людинозрозумілий slug джерела, наприклад `chas-zmin`. |
| `source_url` | required | Абсолютний URL item або detail page. Connector не має створювати item без URL. |
| `canonical_url` | optional, але бажаний | Очищений URL без tracking params. Використовується для deduplication. |
| `source_record_id` | optional, але пріоритетний | Stable id з API/WP/RSS, якщо джерело його дає. |
| `title_hint` | optional, але бажаний | Назва з list/API/RSS. Якщо її немає, item не failed автоматично, але має отримати нижчу якість. |
| `summary_hint` | optional | Короткий опис із list/API/RSS, якщо доступний. |
| `published_at_hint` | optional | Дата публікації з list/API/RSS, якщо джерело її дає. |
| `deadline_hint` | optional | Текстовий дедлайн із list/API/RSS. Не перетворюємо його силоміць у дату на search stage. |
| `listing_url` | optional | URL сторінки або feed, де item був знайдений. |
| `listing_position` | optional | Позиція item у списку під час discovery run. |
| `first_seen_at` | required | Коли item вперше знайдений системою. |
| `last_seen_at` | required | Коли item востаннє бачили в source listing/search. |
| `discovery_status` | required | `new`, `known`, `skipped` або `failed`. |
| `detail_fetch_status` | required | `not_fetched`, `fetched`, `failed` або `skipped_known`. |
| `content_hash` | optional | Hash для fallback identity, особливо якщо немає stable id і URL недостатньо надійний. |
| `discovery_metadata` | required JSON object | Source-specific metadata, quality flags, parser warnings і evidence. |

### Identity Rules

Для безпечного incremental search кожен item має мати стабільну identity.

Пріоритет deduplication:

1. `source_record_id`;
2. `canonical_url`;
3. `content_hash`.

Правила:

- якщо API або WP REST дає id, використовуємо його як `source_record_id`;
- якщо є direct detail URL, зберігаємо його як `source_url` і очищену версію як `canonical_url`;
- якщо item знаходиться на агрегованій сторінці без окремого URL, створюємо `content_hash` із стабільних частин: source slug, title, deadline text, funder або fragment text;
- якщо немає ні `source_record_id`, ні `canonical_url`, ні `content_hash`, item не можна безпечно зберігати як normal discovered item;
- tracking params, session params і pagination params не мають входити в `canonical_url`.

### Null Rules

`null` дозволений, якщо сайт реально не дає поле на search/list рівні.

Не вигадуємо значення для таких полів:

- `title_hint`;
- `summary_hint`;
- `published_at_hint`;
- `deadline_hint`;
- `source_record_id`;
- `canonical_url`.

Не робимо active-only фільтр на search stage. Якщо статус не зрозумілий, зберігаємо `status_hint = "unknown"` у `discovery_metadata`, а фінальний статус визначається пізніше через detail extraction і normalized grant fields.

### Low Quality Vs Failed

`failed` означає, що connector не може створити безпечний candidate item.

Приклади `failed`:

- немає `source_url`;
- немає жодного stable identity key;
- list/API/RSS response не парситься;
- detail link неможливо побудувати;
- source повернув технічну помилку, через яку немає item.

`low_quality` означає, що item можна зберегти, але він потребує обережної обробки.

Приклади `low_quality`:

- є URL, але немає нормального `title_hint`;
- є title, але він дуже generic;
- немає deadline/status hints;
- source category широка і може містити non-grant content;
- item схожий на новину або digest, а не прямий grant competition;
- є підозра на duplicate aggregator content.

### Quality Metadata Contract

На v1 ці flags зберігаються в `discovery_metadata`, а не окремими колонками.

Рекомендована структура:

```json
{
  "discovery_method": "wp_rest",
  "quality_level": "high",
  "quality_reasons": [],
  "is_probably_grant": true,
  "is_probably_grant_reason": "title/category contains grant terms",
  "status_hint": "unknown",
  "deadline_hint_source": "none",
  "requires_manual_review": false,
  "manual_review_reason": null,
  "evidence_text": "short source text used for decision",
  "parser_warnings": []
}
```

Дозволені значення:

- `discovery_method`: `api`, `wp_rest`, `rss`, `sitemap`, `html`, `search_page`, `ai_assisted_html`;
- `quality_level`: `high`, `medium`, `low`;
- `is_probably_grant`: `true`, `false` або `null`;
- `status_hint`: `open`, `closed`, `unknown` або `null`;
- `deadline_hint_source`: `api`, `wp_rest`, `rss`, `html`, `text`, `none`.

### Рішення По Спірних Полях

`quality_score`: не додаємо як DB column у v1. Numeric score буде виглядати точним, хоча фактично правила ще не відкалібровані на всіх сайтах. Використовуємо `quality_level` і `quality_reasons` у `discovery_metadata`.

`is_probably_grant`: не додаємо як DB column у v1. Зберігаємо як hint у `discovery_metadata`. Це не hard filter.

`active_hint`: не використовуємо таку назву, бо ми домовились не робити active-only search. Замість цього використовуємо `status_hint` у `discovery_metadata`, і тільки як підказку.

`requires_manual_review`: не додаємо як DB column у `discovered_grant_items` у v1. Зберігаємо в `discovery_metadata`. У фінальній normalized таблиці `grants` вже є `needs_manual_review` і `manual_review_reason`.

### Quality Gate Для Junior Developer

`high`:

- є `source_url`;
- є `source_record_id` або чистий `canonical_url`;
- є нормальний `title_hint`;
- source category/API endpoint явно grant-related;
- detail fetch очікувано можливий.

`medium`:

- є `source_url`;
- identity стабільна;
- title або summary слабкі, але item схожий на грант;
- status/deadline можуть бути невідомі до detail page.

`low`:

- є URL і identity, але контент шумний;
- title generic;
- deadline/status не видно;
- source є digest/news/aggregator і може давати багато нерелевантних item.

`failed`:

- немає URL;
- немає stable identity;
- неможливо розпарсити listing;
- connector не може безпечно побудувати item.

### Checklist Для `discover()`

Кожен новий connector у `discover()` має зробити такі кроки:

1. Отримати list/API/RSS/sitemap/search response.
2. Витягнути тільки grant-like candidate items, без active-only фільтра.
3. Побудувати абсолютний `source_url`.
4. Побудувати очищений `canonical_url`, якщо є direct detail URL.
5. Заповнити `source_record_id`, якщо API/RSS/WP REST дає stable id.
6. Заповнити `title_hint`, якщо title доступний.
7. Заповнити `summary_hint`, `published_at_hint`, `deadline_hint`, якщо джерело дає ці дані.
8. Заповнити `listing_url` і `listing_position`, якщо item знайдений у списку.
9. Створити `content_hash`, якщо identity слабка або item не має stable id.
10. Записати `discovery_metadata.discovery_method`.
11. Записати `discovery_metadata.quality_level` і `quality_reasons`.
12. Записати `is_probably_grant`, `status_hint`, `requires_manual_review`, якщо connector може це визначити.
13. Не відкидати item тільки тому, що статус або дедлайн невідомі.
14. Не зберігати item, якщо немає безпечної identity.

### Acceptance Step 2

Step 2 закритий, бо:

- визначено фінальний schema description для `discovered_grant_items`;
- визначено required/optional/null правила;
- визначено identity і deduplication правила;
- визначено low quality vs failed;
- визначено quality metadata contract;
- прийнято рішення не додавати `quality_score`, `is_probably_grant`, `active_hint`, `requires_manual_review` як DB columns у v1;
- зафіксовано, що `active-only` не використовується на search stage.

## Реалізовано: Step 3 - Логіка Початкового Наповнення

Статус: виконано як planning/implementation contract.

Дата рішення: `2026-05-23`.

Мета Step 3 була визначити, як саме робити початкове наповнення для кожного джерела: скільки брати записів, які filters використовувати, як не пропустити релевантні grant-like opportunities і як не робити небезпечний active-only filter на search stage.

Важливо: Step 3 не є реалізацією нових конекторів. Він закриває правила, за якими Step 4 має реалізовувати source-specific connectors. Нові production-ready connectors, automated tests і real website validation залишаються в Step 4.

### Головне Правило Початкового Наповнення

Search stage збирає всі релевантні grant-like opportunities, які джерело дозволяє безпечно знайти через API/RSS/WP REST/sitemap/HTML list.

Не відкидаємо item тільки через те, що:

- status не видно на list рівні;
- deadline не видно на list рівні;
- deadline є текстовий або rolling;
- джерело не має structured active/closed state;
- сторінка є digest/news, але містить пряму grant opportunity.

Status і deadline визначаються пізніше:

```text
discover()
  -> status_hint/deadline_hint тільки як підказка
  -> fetch_detail()
  -> normalize()
  -> grants.status / grants.deadline_at / grants.deadline_text
```

### Режими Початкового І Наступного Збору

Початкове наповнення:

```bash
grant-tool ingest --source <slug> --limit <source_limit> --mode backfill
```

Для першого запуску `backfill` потрібен, бо він дозволяє пройти detail-fetch для всіх знайдених item у межах safe limit.

Наступні регулярні запуски:

```bash
grant-tool ingest --source <slug> --limit <source_limit> --mode incremental
```

`incremental` перечитує source listing/search endpoint, але не робить повторний detail-fetch для item, які вже є в `discovered_grant_items`.

Правило для старої сторінки з новим грантом: listing/search endpoint все одно перечитується кожного запуску. Якщо на тій самій сторінці з'явився новий item із новою identity, він буде доданий як новий discovered item. Якщо змінився вже відомий grant, це не задача Step 3; це закривається окремою refresh policy у Step 7.

### Загальні Safe Limits

Ці limits є стартовими правилами для реалізації конекторів. Їх можна зменшувати під час real website validation, якщо сайт повільний або блокує часті запити.

| Тип доступу | Initial backfill v1 | Incremental v1 | Max requests per run | Rate limit |
|---|---:|---:|---:|---:|
| Official API | 100-200 items | 20-50 items | 5-10 API requests | 2-5 sec |
| Public frontend API | 50-100 items | 20-50 items | 5-10 API requests | 5 sec |
| WordPress REST | 50-100 posts | 20-50 posts | 3-6 API requests | 5 sec |
| RSS | feed size або до 50 items | feed size або до 20 items | 1-2 requests | 5 sec |
| Sitemap + HTML detail | 50-100 URLs | 20-50 URLs | 1 sitemap + detail requests only for new items | 5-8 sec |
| HTML list + detail | 20-50 items | 10-20 items | 1-3 list pages + detail requests only for new items | 8-10 sec |
| Restricted/uncertain source | 0 production items | 0 production items | тільки manual validation | conservative |

`--limit` у CLI лишається верхньою межею для конкретного запуску. Connector не має перевищувати цей limit без явної причини.

### Rule Для Grant-Like Filtering

Фільтр має прибирати очевидний шум, але не має вирішувати фінальний статус гранту.

Grant-like item можна брати, якщо виконується хоча б один сильний сигнал:

- URL або category містить grant/грант/конкурс/funding/opportunity;
- title містить grant/funding/call/competition/грант/конкурс/програма підтримки;
- API type явно означає funding opportunity;
- source list уже є grant-specific category;
- detail URL веде на сторінку opportunity/program/competition.

Item треба пропустити на search stage, якщо:

- це service page самого сайту без конкретної opportunity;
- це marketing/blog page без grant opportunity;
- це archive/category/tag page, а не item;
- немає safe identity;
- немає direct detail URL і неможливо створити стабільний item-level hash.

### Source-Specific Initial Collection Rules

| Джерело | Initial backfill rule | Pagination / request limit | Filters без active-only | Status/deadline hints | Причина |
|---|---|---|---|---|---|
| `eu-funding` | Зібрати 100-200 opportunities через official API у межах `--limit`. | 1-2 API pages; `pageSize` не більший за `--limit` для v1. | API query `type in [1,2]`, `programmePeriod = 2021 - 2027`; не фільтрувати тільки active. | Брати deadline/status із API metadata як hints. | Найбільш структуроване джерело, низький noise. |
| `prostir` | Зібрати RSS grant feed до 50-100 items; HTML list тільки fallback. | 1 RSS request; HTML list fallback без глибокого archive crawl. | RSS/category already grant-specific; не відкидати через відсутній deadline у RSS. | Deadline переважно з detail HTML, RSS date тільки `published_at_hint`. | RSS стабільніший за WP grants endpoint. |
| `diia-business` | Зібрати finance API records до 50-100 items. | 1 list API request `take=<limit>, skip=0`; detail fetch тільки для new/backfill items. | Брати finance/program records; не відкидати non-grant finance support на search stage, але ставити quality warning. | `finalProgramTerm` або схожі API attributes як `deadline_hint`; status пізніше. | Frontend API структурований, але містить ширші finance services. |
| `gurt` | Зібрати 20-50 links із `/news/grants/`, якщо runtime access підтверджений або сайт надасть дозволений public endpoint. | 1 HTML list page для v1; pagination тільки після validation. | Path filter `/news/grants/`; не брати header/sidebar/archive links; не обходити Cloudflare/human-check. | Deadline з detail HTML; list status не обов'язковий. | Корисне українське джерело, але production access блокується Cloudflare. |
| `grant-market` | Зібрати 50-100 `/opp/` URLs із sitemap. | 1 sitemap request; detail fetch тільки для new/backfill items. | Sitemap filter тільки `/opp/`; не брати blog/service pages. | Deadline/status з detail HTML. | Sitemap доступний і дає багато opportunity URLs. |
| `chas-zmin` | Зібрати 50-100 WP posts через WP REST або RSS fallback. | WP REST 1-2 pages, `per_page` до 50; RSS fallback 1 request. | Search/category/tag filters для `грант`, `конкурс`, `можливості`; не active-only. | WP date як `published_at_hint`; deadline з content/detail. | WP REST/RSS стабільні, search повертає grant posts. |
| `grantsense` | Не запускати production backfill до підтвердження, що це opportunity source. Manual validation sample до 20 URLs. | 1 sitemap/list sample. | Відкидати service/marketing pages; брати тільки pages із конкретною grant opportunity. | Deadline/status тільки з detail HTML, якщо є. | Високий noise risk після Step 1. |
| `eufundingportal-eu` | Зібрати 50-100 WP posts із funding/grant categories. | WP REST 1-2 pages; RSS fallback 1 request. | Category/tag filters для grants/funding programmes; позначати aggregator duplicate risk. | Deadline/status із WP content/detail, якщо доступні. | Корисний aggregator, але не official EU source. |
| `fundsforngos` | Зібрати 50-100 posts тільки після strong filters. | WP REST 1-2 pages; не crawl whole archive. | Grant keywords + category/topic/country filters; бажано Ukraine/Europe/NGO focus, якщо доступно. | Deadline/status із content/detail. | Багато grant posts, але дуже широкий source і можливий noise/rate-limit. |
| `opportunitydesk` | Зібрати 50 posts після strong filters. | WP REST 1 page або RSS fallback; pagination після validation. | Keywords `grant`, `funding`, `fellowship` тільки якщо релевантно; відкидати education/job noise. | Deadline/status із content/detail. | Opportunity source широкий, потрібне агресивне noise control без active-only. |
| `grantforward` | Production backfill не запускати до detail access check. | Тільки manual validation sample до 10 public detail URLs, якщо знайдені. | Не обходити login/paywall; не scrape restricted results. | Немає надійного правила до access validation. | Високий risk account/institution restriction. |
| `nipo` | Зібрати 50-100 WP posts, але позначати digest/noise risk. | WP REST 1-2 pages; RSS fallback 1 request. | Search/category filters `грант`, `конкурс`, `можливості`, `підтримка`; не брати загальні новини без opportunity. | WP date як `published_at_hint`; deadline з content/detail. | Потенційно корисне digest/news source, але не завжди direct grant pages. |
| `hromady` | Зібрати 50-100 WP posts через WP REST/RSS. | WP REST 1-2 pages; RSS fallback 1 request. | Search/category filters для `грант`, `конкурс`, `підтримка громад`, `можливості`; не active-only. | Deadline/status із detail content. | Добрий кандидат для локальних українських opportunities. |

### Правила Для Джерел Із Високим Noise

Для `fundsforngos`, `opportunitydesk`, `grantsense`, `nipo` і частково `eufundingportal-eu` connector має записувати в `discovery_metadata`:

```json
{
  "quality_level": "medium",
  "quality_reasons": ["aggregator_or_broad_source"],
  "requires_manual_review": true,
  "manual_review_reason": "source can include non-grant or duplicate opportunities"
}
```

Якщо item має сильні grant signals і direct detail page, `requires_manual_review` може бути `false`, але source-level noise risk все одно треба лишити в metadata.

### Правила Для Deferred Sources І Deferred Validation

Deferred source не вважається rejected.

Для повністю deferred джерел:

- не робимо production backfill;
- не додаємо connector як implemented;
- робимо тільки access/detail validation;
- документуємо, що саме не підтверджено;
- переносимо в implementation тільки після підтвердження стабільного list/detail доступу.

Для `gurt` ситуація інша: connector уже існує і локально тестується, але production validation deferred через Cloudflare/human-check. Тому source не rejected і не removed, але його не можна вважати fully production validated.

На поточному етапі це стосується:

- `gurt` production validation, доки не знайдено дозволений спосіб пройти Cloudflare/human-check або альтернативний public endpoint;
- `grantsense`, доки не підтверджено, що source дає конкретні grant opportunities;
- `grantforward`, доки не підтверджено public detail access без login/paywall.

### Acceptance Step 3

Step 3 закритий, бо:

- визначено rule для broad collection без active-only search filter;
- визначено initial backfill і incremental rules;
- визначено safe limits за типом доступу;
- визначено grant-like filtering rules;
- визначено source-specific initial collection rules для всіх джерел із `docs/initial_sources.md`;
- визначено правила для high-noise і deferred sources;
- зафіксовано, що actual connector implementation і real website validation залишаються в Step 4.

## Реалізовано: Step 4.1 - Частина Хвилі 1

Статус: готово для переходу до Step 4.2 після рішення скіпнути GURT production validation на цей момент.

Дата реалізації: `2026-05-23`.

Реалізовано три джерела з хвилі 1:

- `chas-zmin`;
- `eufundingportal-eu`;
- `hromady`.

Після уточнення користувача правильний GURT grants URL - `https://gurt.org.ua/news/grants/`, а не `https://grants.gurt.org.ua/`. Connector `gurt` уже існує з MVP і використовує правильну HTML list strategy, але production live validation не закрита, бо сайт повертає Cloudflare/human-check.

Рішення від `2026-05-23`: GURT скіпається на цей момент і не блокує перехід до наступного step. Він лишається documented deferred/not production validated source.

### Додані Конектори

Додано shared WP REST implementation base:

```text
grant_tool/ingestion/connectors/wordpress.py
```

Це не один універсальний scraper для всіх сайтів. Це спільна реалізація тільки для однотипних WordPress REST джерел, поверх якої є окремі source-specific connector classes:

- `ChasZminConnector`;
- `EUFundingPortalEuConnector`;
- `HromadyConnector`.

Кожен із них використовує той самий погоджений контракт:

```python
discover(limit, mode) -> list[DiscoveredGrantItemDraft]
fetch_detail(discovered_item) -> FetchedDetail
normalize(discovered_item, detail) -> NormalizedGrantDraft
```

### Реалізовано Для `chas-zmin`

Source:

```text
https://chaszmin.com.ua/
```

Поточна стратегія:

- WP REST primary: `https://chaszmin.com.ua/wp-json/wp/v2/posts`;
- RSS fallback: `https://chaszmin.com.ua/feed/`;
- search terms: `грант`, `конкурс`, `можливості`;
- `source_record_id = WP post id`;
- `canonical_url = cleaned WP post link`;
- WP `content.rendered` використовується як detail payload;
- documents, deadline, funding text і status витягуються deterministic helper-ами.

Live validation:

```text
chas-zmin: grants=1 errors=0
```

### Реалізовано Для `eufundingportal-eu`

Source:

```text
https://eufundingportal.eu/
```

Поточна стратегія:

- WP REST primary: `https://eufundingportal.eu/wp-json/wp/v2/posts`;
- RSS fallback: `https://eufundingportal.eu/feed/`;
- search terms: `grant`, `funding`, `programme`;
- `source_record_id = WP post id`;
- `canonical_url = cleaned WP post link`;
- source позначається як aggregator із duplicate risk with official `eu-funding`;
- `needs_manual_review = true` за замовчуванням для normalized grant.

Live validation:

```text
eufundingportal-eu: grants=1 errors=0
```

### Реалізовано Для `hromady`

Source:

```text
https://hromady.org/
```

Поточна стратегія:

- WP REST primary: `https://hromady.org/wp-json/wp/v2/posts`;
- RSS fallback: `https://hromady.org/feed/`;
- search terms: `грант`, `конкурс`, `підтримка громад`, `можливості`;
- `source_record_id = WP post id`;
- `canonical_url = cleaned WP post link`;
- джерело позначається як local/community development source.

Live validation:

```text
hromady: grants=1 errors=0
```

### Source Seeding І Registry

Оновлено source seed definitions:

- додано `chas-zmin`;
- додано `eufundingportal-eu`;
- додано `hromady`;
- `seed-sources` тепер створює або оновлює 7 configured sources: 4 MVP + 3 Step 4.1 sources.

Оновлено connector registry:

- `CONNECTOR_CLASSES["chas-zmin"]`;
- `CONNECTOR_CLASSES["eufundingportal-eu"]`;
- `CONNECTOR_CLASSES["hromady"]`.

### Тести

Додано fixtures:

- `tests/fixtures/chas_zmin/posts.json`;
- `tests/fixtures/eufundingportal_eu/posts.json`;
- `tests/fixtures/hromady/posts.json`.

Додано automated coverage:

- connector parsing test для `chas-zmin`;
- connector parsing test для `eufundingportal-eu`;
- connector parsing test для `hromady`;
- registry test для нових source slugs;
- ingestion service test для WP REST source;
- seed source test оновлено з 4 до 7 configured sources.

Під час тестування знайдено і виправлено deterministic extraction bug: `extract_funding_text` міг брати перше число з дедлайну замість суми фінансування. Тепер helper спершу обирає match із currency/amount marker.

Останній локальний результат:

```text
Ran 51 tests
OK
```

Додаткові перевірки:

```text
python -m compileall grant_tool tests
alembic heads -> 20260522_0004 (head)
```

### GURT Deferred

`gurt` залишається незакритим саме як production validation, бо правильний URL блокується Cloudflare/human-check:

```text
https://gurt.org.ua/news/grants/ -> 403 text/html
https://gurt.org.ua/news/grants/rss/ -> 403 text/html
```

Це не блокує Step 4.2, бо користувач погодив скіпнути GURT на цей момент.

Майбутня дія має бути одна з двох:

- знайти дозволений спосіб доступу до GURT: офіційний RSS/API, allowlist, погоджений user-agent або manual export;
- якщо потрібен четвертий fully validated source у хвилі 1, погодити заміну слота, наприклад на `grant-market`.

Не робимо автоматичний bypass Cloudflare/human-check як частину connector-а.

## Реалізовано: Step 4.2 - Хвиля 2

Статус: виконано для implementable джерел хвилі 2.

Дата реалізації: `2026-05-23`.

У Step 4.2 закрито чотири джерела:

- `nipo` - реалізовано;
- `grant-market` - реалізовано;
- `fundsforngos` - реалізовано;
- `grantsense` - задокументовано як deferred після перевірки на реальному сайті.

### Реалізовано Для `nipo`

Source:

```text
https://nipo.gov.ua/
```

Поточна стратегія:

- WP REST primary: `https://nipo.gov.ua/wp-json/wp/v2/posts`;
- RSS fallback: `https://nipo.gov.ua/feed/`;
- search terms: `грант`, `конкурс`, `можливості`, `підтримка`;
- `source_record_id = WP post id`;
- `canonical_url = cleaned WP post link`;
- WP `content.rendered` використовується як detail payload;
- source позначається як ризик дайджестів/новин;
- `needs_manual_review = true` за замовчуванням для normalized grant.

Причина manual review: NIPO може повертати не тільки прямі grant competitions, а й новини, вебінари або дайджести, які містять інформацію про гранти.

Перевірка на реальному сайті:

```text
nipo: grants=1 errors=0 status=unknown
sample title: SME Fund 2026 для українського бізнесу: підсумки вебінару Talking about my idea (відео, презентації)
```

### Реалізовано Для `grant-market`

Source:

```text
https://grant.market/
```

Поточна стратегія:

- sitemap discovery: `https://grant.market/sitemap.xml`;
- беруться тільки URL-и з path `/opp/`;
- `source_record_id = canonical_url`;
- `canonical_url = cleaned detail URL`;
- detail HTML завантажується окремо;
- title береться з `og:title`, `h1` або `title`;
- summary береться з `og:description` або detail text;
- deadline, documents, funding text і status витягуються deterministic helper-ами.

Додано окремий connector:

```text
grant_tool/ingestion/connectors/grant_market.py
```

Перевірка на реальному сайті:

```text
grant-market: grants=1 errors=0 status=unknown
sample title: Грант на покриття 85% вартості консалтингових проєктів для МСБ
```

### Реалізовано Для `fundsforngos`

Source:

```text
https://www2.fundsforngos.org/
```

Поточна стратегія:

- WP REST primary: `https://www2.fundsforngos.org/wp-json/wp/v2/posts`;
- RSS fallback: `https://www2.fundsforngos.org/feed/`;
- search terms: `grant`, `funding`, `call for proposals`;
- `source_record_id = WP post id`;
- `canonical_url = cleaned WP post link`;
- source позначається як широке міжнародне джерело;
- `needs_manual_review = true` за замовчуванням для normalized grant.

Важлива implementation-деталь: для WP REST джерел normalized title тепер пріоритетно береться з WP API `title.rendered`, а не з HTML `h1`, бо реальний fundsforNGOs detail content може мати generic heading типу `Programme Overview`.

Перевірка на реальному сайті:

```text
fundsforngos: grants=1 errors=0 status=unknown
sample title: CFAs: Artistic Creation Grant for Artists and Arts Organizations (Canada)
```

### GrantSense Deferred

Source:

```text
https://grantsense.com.ua/
```

Рішення: не додано як робочий connector у Step 4.2.

Підтверджена причина:

- sitemap доступний;
- WP REST і RSS не підтверджені як корисні public endpoints;
- sitemap містить службові/категорійні/blog-сторінки, а не стабільний список прямих грантових можливостей;
- перевірені сторінки `grants2024` і `grant/mizhnarodni-granti` повернули Next.js error shell без корисного server-rendered grant content;
- немає безпечного правила для `discover()` без високого noise risk.

Decision:

```text
deferred_after_validation
```

Це не rejected source. Він просто не має достатньо якісного public list/detail механізму для робочого ingestion на цьому кроці.

### Source Seeding І Registry

Оновлено source seed definitions:

- додано `nipo`;
- додано `grant-market`;
- додано `fundsforngos`;
- `grantsense` не додано в seed, бо джерело deferred;
- `seed-sources` тепер створює або оновлює 10 configured sources: 4 MVP + 3 Step 4.1 + 3 Step 4.2 sources.

Оновлено connector registry:

- `CONNECTOR_CLASSES["nipo"]`;
- `CONNECTOR_CLASSES["grant-market"]`;
- `CONNECTOR_CLASSES["fundsforngos"]`.

### Тести

Додано fixtures:

- `tests/fixtures/nipo/posts.json`;
- `tests/fixtures/grant_market/sitemap.xml`;
- `tests/fixtures/grant_market/detail.html`;
- `tests/fixtures/fundsforngos/posts.json`.

Додано automated coverage:

- connector parsing test для `nipo`;
- connector parsing test для `grant-market`;
- connector parsing test для `fundsforngos`;
- registry test для Step 4.2 source slugs;
- ingestion service test для sitemap-based source;
- seed source test оновлено з 7 до 10 configured sources.

Останній локальний результат:

```text
Ran 55 tests
OK
```

Додаткові перевірки:

```text
python -m compileall grant_tool tests
alembic heads -> 20260522_0004 (head)
```

## Реалізовано: Step 4.3 - Хвиля 3

Статус: виконано для джерел хвилі 3.

Дата реалізації: `2026-05-23`.

У Step 4.3 закрито два джерела:

- `opportunitydesk` - реалізовано;
- `grantforward` - задокументовано як deferred/restricted після перевірки на реальному сайті.

### Реалізовано Для `opportunitydesk`

Source:

```text
https://www.opportunitydesk.org/
```

Поточна стратегія:

- WP REST primary: `https://www.opportunitydesk.org/wp-json/wp/v2/posts`;
- RSS fallback: `https://www.opportunitydesk.org/feed/`;
- search terms: `grant`, `funding`, `call for proposals`;
- category filter: `Awards and Grants`, WP category id `29`;
- `source_record_id = WP post id`;
- `canonical_url = cleaned WP post link`;
- WP `content.rendered` використовується як detail payload;
- source позначається як широке opportunity джерело;
- `needs_manual_review = true` за замовчуванням для normalized grant.

Додано source-specific digest filter:

- posts з titles типу `66 Grants...`, `137 Grants...`, `opportunities currently open`, `closing in` не зберігаються як один грант;
- для цього джерела connector бере більший WP REST sample у межах одного search run, щоб після відкидання digest/list posts знайти direct grant-like item.

Причина manual review: Opportunity Desk містить не тільки гранти, а й awards, contests, fellowships, regional opportunities і digest/list posts.

Перевірка на реальному сайті:

```text
opportunitydesk: grants=1 errors=0 status=closed
sample title: UNESCO MAB Young Scientists Awards 2026 (up to $5,000)
```

`status=closed` не є помилкою, бо search stage не робить active-only filter. Статус визначився з дедлайну в detail content.

### GrantForward Deferred

Source:

```text
https://www.grantforward.com/
```

Рішення: не додано як робочий connector у Step 4.3.

Підтверджена причина:

- `https://www.grantforward.com/search` повертає `200 text/html`, але це search UI, а не стабільний public list із direct result links;
- `https://www.grantforward.com/wp-json/wp/v2/posts?per_page=1&search=grant` повертає `404`;
- `https://www.grantforward.com/feed/` повертає `404`;
- `https://www.grantforward.com/sitemap.xml` повертає `404`;
- HTML search page має login/subscription/free trial mechanics;
- у статичному HTML немає direct grant result links, результати завантажуються через JS/search flow;
- немає безпечного public `discover()` без використання restricted/dynamic search behavior.

Decision:

```text
deferred_restricted_after_validation
```

Це не implemented source і не seed source. Його можна повернути в роботу тільки якщо буде знайдено дозволений public endpoint, export, API, sitemap із detail URLs або офіційний доступ.

### Source Seeding І Registry

Оновлено source seed definitions:

- додано `opportunitydesk`;
- `grantforward` не додано в seed, бо джерело deferred/restricted;
- `seed-sources` тепер створює або оновлює 11 configured sources: 4 MVP + 3 Step 4.1 + 3 Step 4.2 + 1 Step 4.3 source.

Оновлено connector registry:

- `CONNECTOR_CLASSES["opportunitydesk"]`.

### Тести

Додано fixture:

- `tests/fixtures/opportunitydesk/posts.json`.

Додано automated coverage:

- connector parsing test для `opportunitydesk`;
- registry test для Step 4.3 source slug;
- seed source test оновлено з 10 до 11 configured sources;
- shared date parser покращено для англійських дат типу `June 21, 2026` і `21 June 2026`.

Останній локальний результат:

```text
Ran 56 tests
OK
```

Додаткові перевірки:

```text
python -m compileall grant_tool tests
alembic heads -> 20260522_0004 (head)
git diff --check -> OK
```

## Реалізовано: Step 5 - Real Website Validation

Статус: виконано.

Дата перевірки: `2026-05-23`.

Мета Step 5 була підтвердити, що connectors працюють не тільки на fixtures, а й на реальних сайтах, і що результат може пройти ingestion flow до `discovered_grant_items`, `raw_grant_snapshots` і `grants`.

### Метод Перевірки

Було виконано два рівні перевірки:

1. Connector-level validation:

```text
Connector.run(limit=1)
  -> discover()
  -> fetch_detail()
  -> normalize()
```

2. Ingestion-level validation на in-memory DB:

```text
seed-sources
  -> IngestionService.run_source(source, limit=1, mode=backfill)
  -> discovered_grant_items
  -> raw_grant_snapshots
  -> grants
  -> job counters
```

`new_count` і `known_count` у цьому step не є фінальним incremental доказом, бо перевірка запускалась у clean in-memory DB. Повна перевірка known/new behavior закрита окремо в Step 6.

### Live Connector Validation Matrix

| Source slug | Access strategy | Discovered / normalized | Errors | Sample status | Sample title | Decision |
|---|---|---:|---:|---|---|---|
| `eu-funding` | `api` | 1 | 0 | `310945031` | Support to the Ministry of Public Administration and Local Self-Government in modernizing the personnel planning procedure | `ready_with_limitations` |
| `prostir` | `rss` | 1 | 0 | `open` | Триває прийом заявок на участь у проєкті U-TEX для організацій підтримки бізнесу | `ready` |
| `diia-business` | `api` | 1 | 0 | `open` | Програма розвитку МСП Сумської області на 2022-2026 роки | `ready_with_limitations` |
| `gurt` | `html` | 0 | 1 | n/a | n/a | `not_publicly_accessible` |
| `chas-zmin` | `wp_rest` | 1 | 0 | `open` | ДО 8 000 ЄВРО - ГРАНТОВА ПРОГРАМА ДЛЯ МІКРОПІДПРИЄМЦІВ ІЗ ПРИФРОНТОВИХ РЕГІОНІВ (НУР) | `ready` |
| `eufundingportal-eu` | `wp_rest` | 1 | 0 | `unknown` | Call for applications to provide access to Advisory Services that enable beneficiaries to prepare green/greener investment projects | `ready_with_limitations` |
| `hromady` | `wp_rest` | 1 | 0 | `open` | Добірка конкурсів та грантових можливостей | `ready_with_limitations` |
| `nipo` | `wp_rest` | 1 | 0 | `unknown` | SME Fund 2026 для українського бізнесу: підсумки вебінару Talking about my idea | `ready_with_limitations` |
| `grant-market` | `sitemap_html` | 1 | 0 | `unknown` | Грант на покриття 85% вартості консалтингових проєктів для МСБ | `ready` |
| `fundsforngos` | `wp_rest` | 1 | 0 | `unknown` | CFAs: Artistic Creation Grant for Artists and Arts Organizations (Canada) | `ready_with_limitations` |
| `opportunitydesk` | `wp_rest` | 1 | 0 | `closed` | UNESCO MAB Young Scientists Awards 2026 (up to $5,000) | `ready_with_limitations` |

### Ingestion-Level Validation Matrix

| Source slug | Job status | Processed | Created | Updated | Skipped | Failed | Errors | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `eu-funding` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready_with_limitations` |
| `prostir` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready` |
| `diia-business` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready_with_limitations` |
| `gurt` | `partial` | 0 | 0 | 0 | 0 | 0 | 1 | `not_publicly_accessible` |
| `chas-zmin` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready` |
| `eufundingportal-eu` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready_with_limitations` |
| `hromady` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready_with_limitations` |
| `nipo` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready_with_limitations` |
| `grant-market` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready` |
| `fundsforngos` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready_with_limitations` |
| `opportunitydesk` | `success` | 1 | 1 | 0 | 0 | 0 | 0 | `ready_with_limitations` |

### Deferred / Restricted Source Evidence

| Source slug | Tested URL | Evidence | Decision |
|---|---|---|---|
| `grantsense` | `https://www.grantsense.com.ua/grants2025` | `500 text/html`; page does not provide stable server-rendered direct opportunity feed. | `deferred` |
| `grantsense` | `https://www.grantsense.com.ua/sitemap.xml` | `200 application/xml`; sitemap exists, but points mostly to service/category/blog pages rather than a reliable direct opportunity feed. | `deferred` |
| `grantsense` | `https://www.grantsense.com.ua/wp-json/` | `404 text/html`; no useful WP REST endpoint. | `deferred` |
| `grantforward` | `https://www.grantforward.com/search` | `200 text/html`; search UI exists, but static HTML has no direct grant result links without JS/search flow. | `deferred_restricted` |
| `grantforward` | `https://www.grantforward.com/wp-json/wp/v2/posts?per_page=1&search=grant` | `404 text/html`; no WP REST posts endpoint. | `deferred_restricted` |
| `grantforward` | `https://www.grantforward.com/sitemap.xml` | `404 text/html`; no public sitemap for direct discovery. | `deferred_restricted` |

### Known Limitations Before Production Use

| Source slug | Limitation | Required follow-up |
|---|---|---|
| `eu-funding` | Live API returned raw status-like value `310945031` as normalized status. | Normalize EU status codes/labels in a later fix or Step 9 cleanup. |
| `diia-business` | Source includes broader business finance/support programmes, not only pure grants. | Keep `support_type` and manual review/feature extraction checks. |
| `gurt` | Cloudflare/human-check returns `403 Forbidden`. | Use only if official/public access path appears; no bypass. |
| `eufundingportal-eu` | Aggregator source can duplicate official EU Funding opportunities. | Keep duplicate risk metadata and manual review. |
| `hromady` | Sample can be digest/list content, not always direct grant detail. | Treat as ready with limitations; quality gate can filter non-grant digest content. |
| `nipo` | News/digest source; sample can be webinar/digest content. | Keep `needs_manual_review`. |
| `fundsforngos` | Broad international source with country/topic mismatch risk. | Keep `needs_manual_review` and strong filters. |
| `opportunitydesk` | Broad opportunity source; sampled item was already `closed`, which is allowed because search does not use active-only filter. | Keep digest filter and manual review. |
| `grantsense` | No stable direct opportunity feed confirmed. | Stay deferred. |
| `grantforward` | Restricted/dynamic search product with login/subscription mechanics. | Stay deferred/restricted. |

### Acceptance Step 5

Step 5 закритий, бо:

- усі configured connectors перевірені на реальних сайтах через connector-level validation;
- 10 із 11 configured connectors пройшли ingestion-level validation із `success`, `processed=1`, `created=1`;
- `gurt` отримав documented live failure `403 Forbidden` і рішення `not_publicly_accessible`;
- `grantsense` і `grantforward` мають documented deferred/restricted evidence;
- для кожного джерела зафіксовано decision;
- список production limitations зафіксовано перед наступними steps.

## Реалізовано: Step 6 - Інкрементальний Збір Тільки Нових Грантів

Статус: виконано.

Дата: `2026-05-24`.

Мета Step 6 - підтвердити, що `incremental` режим не додає повторно ті самі гранти і не робить зайвий detail-fetch для вже відомих item, але все одно перечитує listing/search endpoint кожного запуску.

### Поведінка, Яка Підтверджена

Підтверджений flow:

```text
перший run: mode=backfill
  -> listing/search endpoint читається
  -> item створюється в discovered_grant_items
  -> detail-fetch виконується
  -> raw_grant_snapshots створюється
  -> grants створюється

другий run: mode=incremental
  -> listing/search endpoint читається повторно
  -> item знаходиться як known за stable identity
  -> detail-fetch пропускається
  -> raw_grant_snapshots не дублюється
  -> grants не дублюється і не оновлюється
```

Важливе правило: пропускається не сторінка списку, а тільки вже відомий item. Якщо на тій самій listing page з'явиться новий grant із новою identity, він буде доданий як новий discovered item.

### Що Саме Перевіряє Automated Test

Додано тест:

```text
tests.test_stage3_ingestion.Stage3IngestionTestCase.test_incremental_mode_skips_known_items_for_all_configured_connectors
```

Тест для кожного configured connector виконує:

- перший запуск `IngestionService.run_source(..., mode="backfill")`;
- другий запуск `IngestionService.run_source(..., mode="incremental")`;
- перевірку, що `backfill` створив `created=1`;
- перевірку, що `incremental` дав `processed=1`, `skipped=1`, `created=0`, `updated=0`;
- перевірку, що в БД лишається тільки один `Grant`;
- перевірку, що в БД лишається тільки один `RawGrantSnapshot`;
- перевірку, що в БД лишається тільки один `DiscoveredGrantItem`;
- перевірку, що `detail_fetch_status=skipped_known`;
- перевірку, що `discovery_status=known`;
- перевірку, що `discovery_metadata.last_skip_reason=known_discovered_item`;
- перевірку job metadata: `discovered_count=1`, `new_discovered_count=0`, `known_discovered_count=1`;
- перевірку, що listing/search endpoint викликається мінімум двічі;
- перевірку, що detail endpoint для джерел із окремим detail-fetch викликається тільки один раз за два runs.

### Покриття Джерел

| Source slug | Strategy | Stable identity для known/new decision | Step 6 decision |
|---|---|---|---|
| `eu-funding` | `api` | API record id / identifier | `passed_local_incremental_test` |
| `prostir` | `rss` | RSS GUID або canonical URL | `passed_local_incremental_test` |
| `diia-business` | `api` | service id / slug | `passed_local_incremental_test` |
| `gurt` | `html` | canonical detail URL | `passed_local_incremental_test_with_fixture` |
| `chas-zmin` | `wp_rest` | WordPress post id | `passed_local_incremental_test` |
| `eufundingportal-eu` | `wp_rest` | WordPress post id | `passed_local_incremental_test` |
| `hromady` | `wp_rest` | WordPress post id | `passed_local_incremental_test` |
| `nipo` | `wp_rest` | WordPress post id | `passed_local_incremental_test` |
| `grant-market` | `sitemap_html` | canonical detail URL | `passed_local_incremental_test` |
| `fundsforngos` | `wp_rest` | WordPress post id | `passed_local_incremental_test` |
| `opportunitydesk` | `wp_rest` | WordPress post id | `passed_local_incremental_test` |

`grantsense` і `grantforward` не входять у Step 6 connector test, бо вони не мають реалізованих connectors і вже мають documented deferred/restricted decision.

### Команда Перевірки Step 6

```bash
poetry run python -m unittest tests.test_stage3_ingestion.Stage3IngestionTestCase.test_incremental_mode_skips_known_items_for_all_configured_connectors
```

Результат:

```text
Ran 1 test
OK
```

Повна регресійна перевірка після змін:

```bash
poetry run python -m unittest discover tests
```

Результат:

```text
Ran 57 tests
OK
```

### Acceptance Step 6

Step 6 закритий, бо:

- incremental behavior підтверджено для всіх 11 configured connectors;
- known item не створює дубль `grants`;
- known item не створює дубль `raw_grant_snapshots`;
- known item отримує `detail_fetch_status=skipped_known`;
- listing/search endpoint перечитується повторно, тому нові item на старій сторінці можуть бути знайдені;
- detail-fetch не виконується повторно для known item у звичайному `incremental`;
- `grantsense` і `grantforward` залишаються поза тестом як джерела без connector через documented deferred/restricted decision.

## Реалізовано: Step 7 - Періодичне Оновлення Відомих Open Grants Після Extraction

Статус: виконано.

Дата: `2026-05-24`.

Мета Step 7 - не ламати `incremental new-only` поведінку, але додати контрольований refresh для вже відомих grants, де після extraction може змінитись deadline, status або умови.

### Refresh Policy

Реалізоване правило:

- `open` grant із `deadline_at` оновлюється, якщо `Grant.updated_at` старший за 7 днів;
- `open` або `unknown` grant без `deadline_at` оновлюється, якщо `Grant.updated_at` старший за 14 днів;
- `closed` grants не потрапляють у refresh query;
- source може перевизначити interval через `source_metadata.refresh_open_interval_days`;
- source може перевизначити interval для records без deadline через `source_metadata.refresh_no_deadline_interval_days`;
- fallback `source_metadata.refresh_interval_days` може задати загальний open interval.

### Реалізований Flow

```text
incremental run
  -> connector.discover()
  -> repository.list_discovered_items_due_for_refresh(source_id, policy)
  -> upsert discovered item
  -> якщо item new:
       fetch_detail + normalize + save
  -> якщо item known і не due:
       detail_fetch_status = skipped_known
       job.skipped_count += 1
  -> якщо item known і due:
       fetch_detail + normalize + save
       detail_fetch_status = fetched
       job.updated_count += 1
  -> якщо due item не повернувся в поточному listing:
       refresh виконується напряму через відомий detail/source URL
```

Важливо: listing/search endpoint все одно перечитується кожного incremental run. Refresh decision застосовується тільки після item-level identity match.

### Repository Query

Додано:

```python
GrantRepository.list_discovered_items_due_for_refresh(
    source_id=...,
    now=...,
    limit=...,
    open_interval_days=7,
    no_deadline_interval_days=14,
)
```

Query зв'язує `discovered_grant_items` із `grants` через stable identity:

- `source_record_id`;
- `canonical_url` -> `Grant.source_url`;
- `source_url`.

Це не потребує нової міграції, бо для v1 достатньо існуючих identity fields.

### Job Metadata

Ingestion job тепер записує:

- `refresh_policy`;
- `refresh_due_candidate_count`;
- `refresh_due_count`;
- `refreshed_known_count`;
- `skipped_known_count`;

Приклад:

```json
{
  "refresh_policy": {
    "open_interval_days": 7,
    "no_deadline_interval_days": 14
  },
  "refresh_due_candidate_count": 1,
  "refresh_due_count": 1,
  "refreshed_known_count": 1,
  "skipped_known_count": 0
}
```

### Automated Tests

Додано repository-level test:

```text
tests.test_stage2_repository.RepositoryTestCase.test_stage7_lists_known_items_due_for_refresh
```

Він перевіряє, що old `open` grant без deadline потрапляє в due refresh, а fresh grant не потрапляє.

Додано ingestion-level test:

```text
tests.test_stage3_ingestion.Stage3IngestionTestCase.test_incremental_mode_refreshes_known_open_items_when_due
```

Він перевіряє:

- перший `backfill` створює grant;
- old `open` grant у другому `incremental` проходить refresh;
- detail URL викликається повторно;
- `detail_fetch_status=fetched`;
- `last_refresh_reason=known_item_due_for_refresh`;
- job counters: `updated_count=1`, `skipped_count=0`;
- job metadata: `refresh_due_count=1`, `refreshed_known_count=1`, `skipped_known_count=0`.

Додано ingestion-level test для due item, який не повернувся в поточному listing:

```text
tests.test_stage3_ingestion.Stage3IngestionTestCase.test_incremental_mode_refreshes_due_item_not_present_in_current_listing
```

Він перевіряє:

- другий `incremental` може мати `discovered_count=0`;
- due item усе одно проходить refresh через already known source/detail URL;
- `refresh_source=due_item_not_in_listing`;
- detail URL викликається повторно.

Також повторно перевірено Step 6 behavior:

```text
tests.test_stage3_ingestion.Stage3IngestionTestCase.test_incremental_mode_skips_known_items_for_all_configured_connectors
```

Це підтверджує, що normal known item без due refresh все ще пропускає detail-fetch.

### Команда Перевірки Step 7

```bash
poetry run python -m unittest tests.test_stage2_repository.RepositoryTestCase.test_stage7_lists_known_items_due_for_refresh tests.test_stage3_ingestion.Stage3IngestionTestCase.test_incremental_mode_refreshes_known_open_items_when_due tests.test_stage3_ingestion.Stage3IngestionTestCase.test_incremental_mode_refreshes_due_item_not_present_in_current_listing tests.test_stage3_ingestion.Stage3IngestionTestCase.test_incremental_mode_skips_known_items_for_all_configured_connectors
```

Результат:

```text
Ran 4 tests
OK
```

Повна регресійна перевірка після змін:

```bash
poetry run python -m unittest discover tests
```

Результат:

```text
Ran 60 tests
OK
```

### Acceptance Step 7

Step 7 закритий, бо:

- refresh policy визначена і реалізована;
- repository має query для due refresh items;
- ingestion використовує due refresh без зламу incremental new-only логіки;
- closed grants не оновлюються звичайним refresh query;
- job metadata показує refresh behavior;
- додані automated tests для repository query і ingestion refresh;
- існуючий Step 6 skip-known behavior лишається підтвердженим.

## Реалізовано: Step 8 - Операційна Видимість Search

Статус: виконано.

Дата: `2026-05-24`.

Мета Step 8 - додати швидкий спосіб бачити стан search/link extraction без ручного SQL: скільки item знайдено, скільки grants створено, де є failed detail, skipped known, manual review, refresh activity і останній ingestion job.

### CLI Command

Додано команду:

```bash
grant-tool search-report
```

Фільтр по одному source:

```bash
grant-tool search-report --source prostir
```

Команда читає aggregation із repository і друкує source-level operational table.

### Поля Report-А

Report показує:

- `source`;
- `enabled`;
- `discovered`;
- `grants`;
- `new/known`;
- `detail fetched/skipped/failed`;
- `open/unknown/manual`;
- `latest job`;
- `refresh due/refreshed`;
- `last seen`.

Приклад формату:

```text
Search source report
source | enabled | discovered | grants | new/known | detail fetched/skipped/failed | open/unknown/manual | latest job | refresh due/refreshed | last seen
prostir | yes | 12 | 9 | 2/10 | 9/2/1 | 6/2/1 | success p=12 c=2 u=1 s=9 f=0 | 1/1 | 2026-05-24T12:00:00+00:00
```

### Repository Aggregation

Додано:

```python
GrantRepository.search_source_report(source_slug=None)
```

Метод повертає `SearchSourceReportRow` для кожного source.

Aggregation рахує:

- total discovered items;
- `discovery_status=new`;
- `discovery_status=known`;
- `discovery_status=failed`;
- `detail_fetch_status=not_fetched`;
- `detail_fetch_status=fetched`;
- `detail_fetch_status=failed`;
- `detail_fetch_status=skipped_known`;
- total grants;
- open grants;
- unknown grants;
- grants with `needs_manual_review=true`;
- max `last_seen_at`;
- latest ingestion job counters;
- latest ingestion refresh counters із `job_metadata`.

### Operator Workflow

Після ingestion run оператор має виконати:

```bash
grant-tool search-report
```

Що перевіряти:

- `discovered=0` для source, який мав би працювати, означає проблему з listing/API/search endpoint;
- високий `detail failed` означає проблему з detail pages, selectors, rate limit або access;
- високий `skipped_known` нормальний для stable incremental run;
- `refresh due/refreshed` показує, чи Step 7 refresh реально працює;
- `grants` має рости на backfill або коли з'являються нові grants;
- `open/unknown/manual` допомагає знайти sources із слабкою нормалізацією або високим noise;
- `last seen` показує, чи source реально перечитувався.

Це не замінює Step 9 quality gate на 10 grants. Step 8 тільки дає видимість, щоб бачити, де саме ingestion/search має проблему.

### Automated Tests

Додано repository-level test:

```text
tests.test_stage2_repository.RepositoryTestCase.test_stage8_search_source_report_counts_operational_state
```

Він перевіряє:

- discovered counters;
- new/known counters;
- fetched/skipped detail counters;
- grants/open/unknown/manual counters;
- latest ingestion job status і counters;
- refresh counters із job metadata;
- `last_seen_at`.

Додано CLI formatting tests:

```text
tests.test_stage8_search_report.Stage8SearchReportTestCase
```

Вони перевіряють:

- report header;
- operational columns;
- row format;
- latest job counters;
- refresh due/refreshed counters;
- empty state.

### Команда Перевірки Step 8

```bash
poetry run python -m unittest tests.test_stage2_repository.RepositoryTestCase.test_stage8_search_source_report_counts_operational_state tests.test_stage8_search_report
```

Результат:

```text
Ran 3 tests
OK
```

Повна регресійна перевірка після змін:

```bash
poetry run python -m unittest discover tests
```

Результат:

```text
Ran 63 tests
OK
```

### Acceptance Step 8

Step 8 закритий, бо:

- є CLI command для search operational visibility;
- report показує source-level discovered/grants/status/detail/job/refresh counters;
- є documented operator workflow;
- є automated tests для repository aggregation;
- є automated tests для CLI report format;
- Step 9 quality gate лишається окремим і не вважається виконаним через наявність report-а.

## Ще Не Перенесено В Implemented

Ці частини залишаються в `plan_for_search.md`, бо вони ще не завершені:

- production backfill і quality gate: мінімум 10 quality-approved grants у `grants` для кожного implementable джерела, крім `gurt`;
- фінальне закриття Stage Search.
