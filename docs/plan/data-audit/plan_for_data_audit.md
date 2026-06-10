# План Для Етапу Data Audit І Manual Review

## Призначення Файлу

Цей файл використовується для відкритих пунктів етапу manual review і періодичного data audit.

Правило роботи:

- `plan_for_data_audit.md` містить те, що ще треба реалізувати;
- `implemented_for_data_audit.md` містить тільки те, що вже реалізовано і перевірено;
- після кожного наступного prompt-а виконаний пункт або підпункт переноситься з цього файлу в `implemented_for_data_audit.md`;
- пункт не переноситься в implemented, якщо він тільки обговорений, але ще не реалізований або не перевірений.

## Великий Етап Data Audit / Manual Review

Назва етапу: manual review workflow і періодичний data audit.

Мета етапу - перетворити records, які Data Preparation stage позначив як `needs_review`, на придатні або явно відхилені records через контрольований human-in-the-loop workflow, і зробити audit якості даних повторюваною операційною практикою, а не одноразовою перевіркою.

Цей етап не про те, щоб знайти більше грантів і не про те, щоб змінювати deterministic normalization. Search stage і Data Preparation stage закриті.

Етап працює з результатом, який уже є в `grants`:

- persisted `quality_score`, `quality_tier`, `quality_flags`;
- `needs_manual_review` і `manual_review_reason`;
- `extraction_metadata.quality` з explainable breakdown;
- `extraction_metadata.deduplication`.

## Початковий Стан (Baseline 2026-06-10)

Фактичний стан локального dataset на момент закриття Data Preparation stage:

- total grants: `419`;
- tier `needs_review`: `266 (63.5%)`;
- tier `usable_with_warnings`: `139`;
- tier `noise_rejected`: `14`;
- matching ready: `128`;
- explicit `needs_manual_review`: `275`;
- середній quality score: `57.6`;
- records зі score нижче 40: `14`.

Головна проблема етапу: 266 records у `needs_review` не потрапляють у matching, і без human review вони ніколи звідти не вийдуть.

## Початкові Вимоги

Етап має закрити такі задачі:

1. Визначити, які records переглядати першими, через deterministic пріоритезацію review queue.
2. Визначити контракт review decision: які рішення може прийняти людина і що кожне рішення змінює.
3. Зберігати review decisions так, щоб re-extraction і re-scoring ніколи не перезаписували людське рішення.
4. Дати операційний workflow для review: спочатку CLI, потім dashboard UI.
5. Інтегрувати review decisions у quality score, tier і matching gate.
6. Зробити audit повторюваним: порівняння якості між runs, видимі деградації після нових ingestion runs.
7. Визначити production readiness gate для даних.

## Архітектурне Правило

Людське рішення має пріоритет над deterministic pipeline.

Ключові правила:

- review decision зберігається окремо від полів, які перераховує Stage 5 extraction; `extract-features` reset/recompute не може його стерти;
- precedence: human decision > deterministic rules > AI fallback;
- decisions не видаляють records і не видаляють raw data; reject - це soft-reject через status/tier;
- кожне рішення traceable: хто, коли, яке рішення, причина;
- decision можна скасувати (reset), і це теж traceable;
- deterministic правила лишаються першим шаром для нових records; review потрібен тільки там, де rules непевні;
- CLI workflow реалізується раніше за UI, як і на попередніх етапах;
- periodic audit не змінює дані, тільки вимірює.

Правильний flow для цього етапу:

```text
quality_tier = needs_review
  -> deterministic review queue priority
  -> human decision (CLI або dashboard)
  -> persisted review decision (окремо від extraction fields)
  -> recompute quality score з урахуванням decision
  -> record потрапляє в prepared set або стає soft-rejected
  -> periodic audit порівнює quality між runs
```

Що не робимо на цьому етапі:

- не переписуємо normalization і classification rules без повторного audit evidence;
- не додаємо нові sources;
- не видаляємо noise records фізично;
- не робимо AI auto-review першим шаром (AI assist можливий тільки як підказка для людини);
- не редагуємо дані ad-hoc прямо в таблиці.

## Step 1: Review Queue Baseline

Мета: зафіксувати baseline і дати deterministic, пріоритезовану чергу records для review без зміни schema.

Потрібно:

- deterministic правила пріоритету review queue, наприклад:
  - спочатку records з високим quality score, які блокує тільки manual review (найдешевший виграш для matching set);
  - потім records зі структурованих і useful sources (`source_family`);
  - digest-heavy noise candidates - в кінці;
- read-only CLI:
  - `grant-tool review-queue`;
  - `grant-tool review-queue --source <slug> --limit N`;
- queue показує: title, source, score, tier, flags, manual_review_reason, причину пріоритету;
- baseline метрики зафіксовані в `implemented_for_data_audit.md` після реалізації.

Acceptance:

- queue deterministic і пояснюваний;
- schema не змінюється;
- є tests на ordering rules;
- CLI працює на live Docker dataset.

## Step 2: Review Decision Contract

Мета: визначити app-facing контракт людського рішення до того, як з'являться DB поля.

Потрібно визначити і задокументувати:

- decision values, наприклад:
  - `approved` - record підтверджений як grant/opportunity, придатний для matching;
  - `rejected_noise` - підтверджений non-grant/noise;
  - `rejected_irrelevant` - grant, але не релевантний для клієнтів tool-а;
  - `needs_data_fix` - record справжній, але дані треба виправити на рівні source/extraction;
- що кожне decision змінює:
  - вплив на tier, score, flags, matching eligibility;
  - `approved` знімає manual review блокування;
  - `rejected_*` працює як постійний soft-reject;
- precedence rules відносно deterministic pipeline і AI fallback;
- правила скасування рішення (`reset`) і повторного review;
- хто може бути reviewer (operator identifier, без зберігання зайвих персональних даних).

Acceptance:

- контракт задокументований у `docs/plan/data-audit/review_decision_contract.md`;
- контракт виражений як pure code-level enum/evaluator з tests;
- schema ще не змінюється.

## Step 3: Persisted Review Decisions

Мета: зберігати рішення так, щоб pipeline їх ніколи не перезаписував.

Потрібно:

- Alembic migration:
  - окрема таблиця `grant_review_decisions` (grant_id, decision, reviewer, reason, decided_at, supersedes/active flag) як audit trail;
  - denormalized поточний стан на `grants` (наприклад `review_status`), щоб matching/dashboard не робили join на кожен record;
- integration:
  - `extract-features` і `deduplicate` не торкаються review полів;
  - `quality-score` враховує active decision (Step 6 інтеграція формалізує правила);
- repository методи для запису/читання decisions;
- migration має робочий downgrade.

Acceptance:

- рішення переживає повторний `extract-features`, `deduplicate`, `quality-score` (покрито tests);
- історія рішень не губиться при зміні рішення;
- schema зміни мінімальні і задокументовані в `docs/fields.md`.

## Step 4: Review CLI Workflow

Мета: дати операційний спосіб приймати рішення без UI.

Потрібно:

- CLI команди:
  - `grant-tool review list` (queue з Step 1 + review_status);
  - `grant-tool review show <grant-id>` (повний context: поля, score breakdown, flags, snapshot evidence);
  - `grant-tool review approve <grant-id> --reason ...`;
  - `grant-tool review reject <grant-id> --decision rejected_noise|rejected_irrelevant --reason ...`;
  - `grant-tool review reset <grant-id> --reason ...`;
- після decision - автоматичний recompute persisted quality score для record;
- зрозумілий output: що змінилось (tier/score/matching eligibility).

Acceptance:

- повний review cycle можливий тільки через CLI;
- кожна команда traceable через decisions table;
- є tests на approve/reject/reset flow;
- CLI перевірений на live Docker dataset.

## Step 5: Dashboard Review UI

Мета: зробити review зручним для щоденної роботи через існуючий FastAPI/Jinja2/HTMX dashboard.

Потрібно:

- сторінка `/review`:
  - черга з пріоритетом Step 1, фільтри по source/tier/flag;
  - detail view з evidence: summary/description, score breakdown з `extraction_metadata.quality`, flags, dedup info, лінк на source;
  - HTMX дії approve/reject/reset без перезавантаження сторінки;
- reviewed records видно окремо від pending;
- лічильник queue на overview сторінці;
- POST endpoints використовують ту саму service логіку, що й CLI (без дублювання правил).

Acceptance:

- review повного циклу можливий через браузер;
- рішення з UI ідентичні рішенням з CLI на рівні даних;
- є tests на routes;
- UI перевірений на live Docker dataset.

## Step 6: Review Integration У Score І Matching

Мета: формалізувати вплив рішень на quality score, tier і matching.

Потрібно:

- scoring:
  - `approved` - знімає manual review penalty і `needs_manual_review` блокування; score перераховується;
  - `rejected_noise` / `rejected_irrelevant` - tier поводиться як `noise_rejected` незалежно від тексту;
  - `needs_data_fix` - record лишається поза matching, але з окремим flag;
- matching gate:
  - reviewed-rejected records ніколи не потрапляють у matching, навіть з `--include-low-quality`;
  - `approved` records проходять gate, якщо інші hard filters (deadline, country, type) не блокують;
- dashboard prepared/quality фільтри враховують review_status;
- `scoring`/`contract` версії оновлені, breakdown в `extraction_metadata.quality` показує вплив review.

Acceptance:

- вплив кожного decision на score/tier/matching покритий tests;
- explainability збережена (видно, що рішення людини змінило результат);
- існуючі tests Data Preparation stage не ламаються.

## Step 7: Periodic Audit І Quality Trend Report

Мета: зробити audit повторюваною практикою і бачити динаміку якості між runs.

Потрібно:

- зберігати агрегований snapshot метрик кожного `quality-score` run у `job_metadata` (вже частково є: tier_counts, low_score_count) і доформалізувати склад метрик;
- CLI report:
  - `grant-tool quality-trend` (порівняння останніх N quality-score runs: total, tiers, avg score, low score, review queue size, по source);
  - explainable deltas: які sources деградували/покращились;
- операційна процедура в `docs/operations.md`:
  - після кожного ingestion run: `extract-features` -> `deduplicate` -> `quality-score` -> `quality-trend`;
  - коли дивитися `data-audit` повний report;
- рекомендована частота і trigger-и для повторного review.

Acceptance:

- trend report працює на історії JobRun без нової таблиці, або рішення про нову таблицю задокументоване;
- деградація якості після ingestion run видима без ручного порівняння;
- процедура задокументована в operations.md;
- є tests на формування report.

## Step 8: Production Readiness Gate Для Даних

Мета: визначити вимірюваний критерій, коли дані можна вважати production ready для matching і AI-рекомендацій.

Потрібно:

- визначити gate правила, наприклад:
  - частка scored records = 100% або documented reason;
  - review queue не більша за визначений поріг;
  - zero reviewed-rejected records у prepared set;
  - мінімальна кількість matching ready records на required source;
- CLI:
  - `grant-tool data-readiness` з pass/blocked статусом і поясненням по кожному правилу;
  - non-zero exit code для CI-style використання, з `--no-fail` опцією як у `quality-gate`;
- пороги конфігуровані і задокументовані.

Acceptance:

- gate deterministic і пояснюваний;
- є tests;
- gate перевірений на live Docker dataset;
- значення порогів задокументовані разом з обґрунтуванням.

## Коли Етап Data Audit / Manual Review Може Бути Завершений

Етап можна вважати завершеним тільки тоді, коли:

1. Є deterministic пріоритезована review queue.
2. Review decision contract визначений і задокументований.
3. Decisions persisted, traceable і переживають будь-який pipeline re-run.
4. Повний review cycle можливий через CLI і через dashboard.
5. Decisions інтегровані в score, tier і matching gate.
6. Audit повторюваний, з видимим quality trend між runs.
7. Є production readiness gate з документованими порогами.
8. Є automated tests на всі рівні (contract, persistence, CLI, UI, integration).
9. Review queue на поточному dataset фактично відпрацьована або свідомо обмежена документованим рішенням.

## Поточний Plan State

Жоден step ще не реалізований.

Відкриті steps:

- Step 1: Review Queue Baseline;
- Step 2: Review Decision Contract;
- Step 3: Persisted Review Decisions;
- Step 4: Review CLI Workflow;
- Step 5: Dashboard Review UI;
- Step 6: Review Integration У Score І Matching;
- Step 7: Periodic Audit І Quality Trend Report;
- Step 8: Production Readiness Gate Для Даних.

Перший рекомендований prompt для реалізації:

```text
implement step 1 for data audit stage
```
