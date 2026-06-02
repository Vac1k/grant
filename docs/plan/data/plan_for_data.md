# План Для Підготовки Даних Грантів

## Призначення Файлу

Цей файл використовується для відкритих пунктів етапу підготовки даних у таблиці `grants`.

Правило роботи:

- `plan_for_data.md` містить те, що ще треба реалізувати;
- `implemented_for_data.md` містить тільки те, що вже реалізовано і перевірено;
- після кожного наступного prompt-а виконаний пункт або підпункт переноситься з цього файлу в `implemented_for_data.md`;
- пункт не переноситься в implemented, якщо він тільки обговорений, але ще не реалізований або не перевірений.

## Великий Етап Data Preparation

Назва етапу: підготовка даних грантів і якість нормалізації.

Мета етапу - привести вже знайдені записи в `grants` до стану, де їх можна надійно використовувати для matching, scoring, dashboard і AI-рекомендацій.

Цей етап не про те, щоб знайти більше грантів. Пошук і link extraction уже закриті окремим Stage Search.

Цей етап працює з результатом, який уже потрапив у:

- `discovered_grant_items`;
- `raw_grant_snapshots`;
- `grants`.

Основний фокус етапу - таблиця `grants`.

## Початкові Вимоги

Етап має закрити такі задачі:

1. Очистити `grants` від шуму.
2. Покращити заповненість полів.
3. Уніфікувати статуси, дедлайни, валюти, суми, країни, регіони, funder і eligibility.
4. Позначити слабкі записи для manual review.
5. Видалити або відокремити non-grant records.
6. Підготувати дані до matching з клієнтами.
7. Додати вимірювану якість записів, щоб було видно, які grants готові до використання, а які потребують перевірки.

## Архітектурне Правило

Не змінюємо search stage, якщо проблема знаходиться в якості normalized data.

`grants` лишається широкою normalized таблицею. Це не означає, що кожне джерело повинно заповнювати кожне поле.

Через різну якість джерел не можна вимагати 100% заповнення всіх grant fields:

- API може давати структуровані fields;
- WordPress часто дає title і content, але не дає funder або amount окремо;
- RSS може давати тільки title, link і short summary;
- sitemap/HTML може давати тільки URL і raw text;
- GrantForward дає public search fields, але detail pages login-only;
- NIPO/Hromady можуть давати digest/news-like content.

Правильне правило:

```text
усі grants повинні мати core fields
інші fields заповнюються best-effort
якість запису оцінюється через quality score, quality flags і manual review
```

Не можна змушувати connector вигадувати дані, якщо source їх не дав. Якщо поле не можна надійно витягнути, воно лишається пустим або отримує quality flag/manual review reason.

Правильний flow для цього етапу:

```text
raw_grant_snapshots
  -> existing normalized grants
  -> audit current grant quality
  -> deterministic normalization rules
  -> optional AI fallback for weak fields
  -> quality score and quality flags
  -> prepared grant records for matching/dashboard
```

Що стандартизуємо:

- правила якості grant record;
- статуси;
- дедлайни;
- валюти і суми;
- країни і регіони;
- funder;
- support type;
- eligibility;
- classification;
- manual review reasons;
- duplicate candidates;
- quality score;
- quality flags.

Що не робимо на цьому етапі:

- не додаємо нові сайти;
- не переписуємо connectors без причини;
- не робимо AI першим шаром extraction;
- не видаляємо raw data;
- не приховуємо noise без пояснюваного статусу або flag.

## Висновки З Live Audit Step 1

Step 1 показав, що app-level проблема зараз не тільки в незаповнених полях, а в ризику використати шумні записи в matching і рекомендаціях.

Фактичний результат live audit на локальній Postgres БД:

- total grants: `419`;
- manual review: `275/419 (65.6%)`;
- weak records: `419/419 (100.0%)`;
- noise candidates: `236/419 (56.3%)`.

Наслідки для плану:

- quality contract має бути app-facing, а не тільки field-completeness checklist;
- noise classification і matching gate мають бути визначені до глибокої нормалізації;
- `funder_name`, `regions`, `application_url`, `published_at` не можна робити hard-required для всіх sources, бо це відкине майже весь dataset;
- відсутність цих fields має давати quality flags, lower score або manual review, але не автоматичний reject;
- matching має брати тільки записи, які не classified як noise і мають minimum usable context.

Source-level strategy з audit:

- direct/structured або відносно чисті sources:
  - `diia-business`;
  - `eu-funding`.
- useful but incomplete sources:
  - `chas-zmin`;
  - `grant-market`;
  - `prostir`.
- noisy або digest-heavy sources, які потребують раннього classification gate:
  - `nipo`;
  - `hromady`;
  - `fundsforngos`;
  - `opportunitydesk`;
  - `eufundingportal-eu`.
- empty/problem source у поточному dataset:
  - `gurt`.

## Step 3: Noise Classification And Matching Gate

Мета: рано відокремити справжні grant/support opportunities від шуму, щоб app і matching не працювали по news/digest/webinar/event/article records.

Цей крок піднятий перед глибокою нормалізацією, бо live audit показав `236/419 (56.3%)` noise candidates.

Класифікації:

- `grant`;
- `business_support`;
- `finance_program`;
- `opportunity`;
- `digest`;
- `news`;
- `article`;
- `event`;
- `webinar`;
- `training`;
- `tender`;
- `unknown`.

Потрібно реалізувати:

- deterministic rules для очевидного noise;
- source-specific hints для шумних джерел;
- manual review reason для непевних records;
- окремий flag/tier для records, які не треба використовувати в matching;
- matching gate, який може відфільтрувати `noise_rejected` і `needs_review` без видалення raw data.

Особливо перевірити:

- `nipo`;
- `hromady`;
- `prostir`;
- `fundsforngos`;
- `opportunitydesk`;
- `eufundingportal-eu`;
- `grant-market`.

Acceptance:

- noisy records не потрапляють у prepared matching set без flag/tier;
- classification пояснювана;
- є tests для digest/news/webinar/article/event/training cases;
- source-specific noise behavior покритий tests;
- зміни не ламають існуючий ingestion;
- raw records не видаляються.

## Step 4: Normalize Critical Fields

Мета: привести ключові поля `grants` до стабільного формату для records, які не відкинуті раннім noise gate.

Поля для нормалізації:

- `status`;
- `deadline_at`;
- `deadline_text`;
- `funding_amount_text`;
- `currency`;
- `country`;
- `region`;
- `funder_name`;
- `support_type`;
- `eligibility_text`.

Потрібно реалізувати:

- нормалізацію статусів до `open`, `closed`, `unknown`;
- deadline parser для типових форматів;
- extraction currency з amount text;
- очищення amount text від зайвого HTML/text noise;
- source-level fallback для funder, якщо сайт не дає окремий funder;
- basic country/region inference;
- support type inference;
- eligibility cleanup.

Normalization не має вигадувати дані без source evidence. Якщо поле не можна витягнути надійно, record отримує quality flag, lower score або manual review reason.

Acceptance:

- нормалізація покрита tests;
- зміни не ламають існуючий ingestion;
- raw value не губиться, якщо normalized value непевний;
- weak records отримують manual review reason або quality flag;
- global hard requirement не вводиться для `funder_name`, `regions`, `application_url`, `published_at`.

## Step 5: Deduplication

Мета: знайти дублікати між джерелами і всередині одного джерела.

Особливо перевірити:

- `eu-funding` і `eufundingportal-eu`;
- aggregator sources;
- записи з однаковим title;
- записи з однаковим deadline і funder;
- записи з різними URL, але однаковим змістом;
- записи з однаковим normalized external id, якщо він є.

Потрібно реалізувати:

- duplicate candidate detection;
- пояснюваний duplicate score;
- flag для potential duplicate;
- правило, який record вважати primary;
- зв'язок duplicate records з primary record або окрема таблиця duplicate groups.

Acceptance:

- duplicates не видаляються без trace;
- duplicate candidates можна перевірити;
- є tests на exact і fuzzy duplicate cases;
- matching layer може ігнорувати duplicate records або використовувати primary.

## Step 6: AI Fallback For Extraction

Мета: використовувати AI тільки там, де deterministic extraction недостатній.

AI не використовується для search crawling.

AI може допомагати:

- витягнути eligibility;
- коротко описати grant;
- визначити країну або регіон;
- визначити target audience;
- класифікувати, чи це справжній grant;
- пояснити, чому record потребує manual review;
- заповнити слабкі поля з raw text.

Потрібно реалізувати:

- правило, коли AI fallback дозволений;
- prompt contract;
- schema для AI result;
- confidence або reason fields;
- збереження AI output окремо від raw site data;
- можливість вимкнути AI fallback.

Acceptance:

- AI не перезаписує deterministic fields без правила;
- AI output traceable;
- є fallback behavior без API key;
- є tests для schema validation;
- manual review reason пояснює AI uncertainty.

## Step 7: Quality Score

Мета: додати вимірювану якість кожного grant record.

Потрібно додати або підготувати:

```text
quality_score: 0-100
quality_flags:
  - missing_deadline
  - missing_amount
  - missing_funder
  - missing_country
  - missing_region
  - missing_eligibility
  - missing_application_url
  - missing_published_at
  - broad_finance_program
  - possible_digest
  - possible_news
  - possible_event
  - possible_webinar
  - possible_training
  - possible_duplicate
  - needs_manual_review
  - noise_rejected
```

Score має враховувати:

- заповненість core fields;
- заповненість important optional fields;
- відсутність advanced fields тільки як слабкий сигнал, а не як причина reject;
- тип джерела;
- classification;
- duplicate risk;
- manual review;
- наявність deadline;
- наявність summary/full text;
- чи record придатний для matching.

Acceptance:

- score deterministic;
- flags explainable;
- є CLI або report для перегляду score;
- records з низьким score не використовуються в matching без явного дозволу.

## Step 8: Prepared Grants Layer

Мета: створити зручний шар даних для matching, scoring, dashboard і AI-рекомендацій.

Варіанти реалізації:

- додаткові поля в `grants`;
- окрема таблиця `prepared_grants`;
- materialized view;
- regular SQL view.

Початкова рекомендація:

- не створювати окрему таблицю одразу;
- спочатку додати audit, quality contract, noise/matching gate, normalization, flags і score;
- після цього вирішити, чи потрібна `prepared_grants`.

Acceptance:

- є зрозумілий prepared set для matching;
- dashboard може показувати quality state;
- manual review records видно окремо;
- non-grant/noise records не змішуються з якісними grants;
- рішення про table/view/fields задокументоване.

## Коли Етап Data Preparation Може Бути Завершений

Етап можна вважати завершеним тільки тоді, коли:

1. Поточні дані в `grants` проаудитовані.
2. Quality contract визначений і задокументований.
3. Noise records класифікуються і не потрапляють у prepared matching set без flag/tier.
4. Критичні поля нормалізуються стабільно.
5. Duplicate candidates виявляються і не гублять trace.
6. AI fallback, якщо доданий, працює тільки як контрольований fallback, а не як перший шар.
7. Кожен grant має quality score або documented reason, чому score не розрахований.
8. Є prepared data layer або задокументоване рішення лишити prepared fields у `grants`.
9. Є automated tests.
10. Є операційна команда або report для перевірки якості даних.

## Поточний Plan State

Step 1 і Step 2 виконані та перенесені у `implemented_for_data.md`.

Відкриті steps:

- Step 3: Noise Classification And Matching Gate;
- Step 4: Normalize Critical Fields;
- Step 5: Deduplication;
- Step 6: AI Fallback For Extraction;
- Step 7: Quality Score;
- Step 8: Prepared Grants Layer.

Перший рекомендований prompt для реалізації:

```text
implement step 3 for data preparation
```
