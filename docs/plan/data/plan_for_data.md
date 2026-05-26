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

## Step 1: Audit Current Grant Data

Мета: зрозуміти, що реально лежить у `grants` після завершеного search stage.

Треба перевірити:

- скільки записів є по кожному source;
- які поля часто пусті;
- де `status = unknown`;
- де немає `deadline_at`;
- де немає `funder_name`;
- де немає `funding_amount_text`;
- де немає `currency`;
- де немає `country` або `region`;
- де немає `eligibility_text`;
- скільки записів мають `needs_manual_review = true`;
- які записи схожі на news, digest, article, webinar або broad finance page;
- які джерела дають найбільше шуму;
- які джерела дають найкращу заповненість.

Очікуваний результат:

- CLI або SQL audit report;
- документація з фактичним станом `grants`;
- список слабких полів;
- список шумних джерел;
- список джерел, які вже дають якісні records;
- рішення, які поля нормалізувати першими.

Acceptance:

- audit запускається локально;
- audit показує статистику по source;
- audit показує field completeness;
- audit показує manual review ratio;
- audit показує noise candidates;
- результати перенесені в `implemented_for_data.md`.

## Step 2: Define Grant Quality Contract

Мета: визначити, що таке якісний grant record для нашої системи.

Потрібно описати minimum quality contract для `grants` і розділити поля на три рівні.

### Core Fields

Ці поля потрібні майже завжди. Без них record важко використовувати в системі:

- `title`;
- `source_url`;
- `source_id`;
- `source_slug`;
- `summary` або інший достатній text field;
- `status` у дозволеному форматі;
- `needs_manual_review`;
- `manual_review_reason`, якщо потрібна ручна перевірка.

### Important But Optional Fields

Ці поля дуже корисні для matching і dashboard, але не всі джерела можуть дати їх надійно:

- `deadline_at`;
- `deadline_text`;
- `funder_name`;
- `funding_amount_text`;
- `currency`;
- `country`;
- `region`;
- `support_type`;
- `eligibility_text`;
- `application_url`;
- `source_published_at`.

Їх треба витягувати, коли source реально дає достатньо даних. Не треба заповнювати ці поля шумом або припущенням тільки для того, щоб поле не було пустим.

### Advanced / Enrichment Fields

Ці поля покращують matching, scoring і AI-рекомендації, але не мають бути required для ingestion:

- `funding_amount_min`;
- `funding_amount_max`;
- `opportunity_type`;
- `program_name`;
- `keywords`;
- `restrictions_text`;
- `cofinancing_required`;
- `cofinancing_text`;
- `consortium_required`;
- `consortium_text`;
- `implementation_period_text`;
- `contact_text`;
- `documents`;
- `extraction_confidence`;
- `extraction_metadata`;
- `embedding`;
- `embedding_text`;
- `embedding_model`;
- `embedded_at`.

Ці поля можна покращувати пізніше через deterministic normalization або AI fallback.

Потрібно визначити:

- які поля є критичними;
- які поля можуть бути пустими;
- які пусті поля мають давати quality flag;
- які пусті поля мають переводити record у manual review;
- які поля не можна штучно заповнювати без source evidence;
- які записи можна вважати non-grant;
- які записи можна лишати як broader support program.

Acceptance:

- quality contract описаний у документації;
- contract можна використати в коді;
- поля розділені на core, important optional і advanced/enrichment;
- є список allowed statuses;
- є список quality flags;
- є список classification values;
- є правила для manual review.

## Step 3: Normalize Critical Fields

Мета: привести ключові поля `grants` до стабільного формату.

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

Acceptance:

- нормалізація покрита tests;
- зміни не ламають існуючий ingestion;
- raw value не губиться, якщо normalized value непевний;
- weak records отримують manual review reason або quality flag.

## Step 4: Deduplication

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

## Step 5: Noise Classification

Мета: відокремити справжні гранти від шуму.

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
- `unknown`.

Потрібно реалізувати:

- deterministic rules для очевидного noise;
- source-specific hints для шумних джерел;
- manual review reason для непевних records;
- окремий flag для records, які не треба використовувати в matching.

Acceptance:

- noisy records не потрапляють у prepared matching set без flag;
- classification пояснювана;
- є tests для digest/news/webinar/article cases;
- `hromady`, `nipo`, `fundsforngos`, `opportunitydesk` перевірені окремо.

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
  - missing_eligibility
  - broad_finance_program
  - possible_digest
  - possible_news
  - possible_duplicate
  - needs_manual_review
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
- спочатку додати audit, quality contract, normalization, flags і score;
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
3. Критичні поля нормалізуються стабільно.
4. Duplicate candidates виявляються і не гублять trace.
5. Noise records класифікуються і не потрапляють у prepared matching set без flag.
6. AI fallback, якщо доданий, працює тільки як контрольований fallback, а не як перший шар.
7. Кожен grant має quality score або documented reason, чому score не розрахований.
8. Є prepared data layer або задокументоване рішення лишити prepared fields у `grants`.
9. Є automated tests.
10. Є операційна команда або report для перевірки якості даних.

## Поточний Plan State

Відкриті всі steps цього етапу.

Перший рекомендований prompt для реалізації:

```text
implement step 1 for data preparation
```
