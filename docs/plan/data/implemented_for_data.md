# Виконано Для Підготовки Даних Грантів

## Призначення Файлу

Цей файл є єдиним місцем, куди переноситься все, що вже реалізовано для етапу підготовки даних грантів.

Правило роботи з файлами:

- `plan_for_data.md` містить те, що ще треба зробити;
- `implemented_for_data.md` містить тільки те, що вже реалізовано і перевірено;
- після кожного наступного prompt-а виконаний пункт або підпункт переноситься з `plan_for_data.md` у цей файл;
- пункт не переноситься сюди, якщо він тільки обговорений, але ще не реалізований або не перевірений.

## Поточний Статус Етапу Data Preparation

Етап підготовки даних грантів завершений.

Фактичний стан:

- Stage Search / Link Extraction завершений;
- дані вже потрапляють у `discovered_grant_items`, `raw_grant_snapshots` і `grants`;
- Step 1 audit поточного стану таблиці `grants` реалізований як read-only CLI/report;
- Step 2 quality contract реалізований як документація і pure code-level evaluator;
- Step 3 noise classification і matching gate реалізовані;
- Step 4 critical field normalization реалізований у deterministic extraction flow;
- Step 5 deduplication реалізований як soft-dedup metadata layer і matching gate;
- Step 6 AI fallback for extraction реалізований як контрольований optional fallback;
- Step 7 quality score реалізований як persisted deterministic score/tier/flags;
- Step 8 prepared grants layer реалізований як persisted quality fields у `grants` плюс repository prepared set і dashboard quality state;
- додатково проведена ревізія полів БД: видалені overengineered поля і таблиця `reports`.

## Реалізовано

### Step 1: Audit Current Grant Data

Статус: реалізовано.

Дата реалізації: `2026-06-02`.

Дата Docker/live validation: `2026-06-02`.

Мета Step 1 була отримати фактичний audit normalized таблиці `grants` без зміни schema і без втручання в search/ingestion stage.

Реалізовано read-only CLI:

```bash
grant-tool data-audit
grant-tool data-audit --source nipo
grant-tool data-audit --sample-limit 10
```

Що показує audit:

- кількість `grants` по кожному source;
- status distribution по source;
- manual review ratio;
- field completeness для:
  - `source_url`;
  - `title`;
  - `status_known`;
  - `summary_or_description`;
  - `deadline_at`;
  - `deadline_text`;
  - `funder_name`;
  - `funding_amount_text`;
  - `currency`;
  - `countries`;
  - `regions`;
  - `eligibility_text`;
  - `application_url`;
  - `published_at`;
- слабкі записи з пояснюваними reasons;
- noise candidates з пояснюваними reasons;
- sample weak/noise records для ручної перевірки.

Реалізаційні файли:

- `grant_tool/db/repositories.py`:
  - `DataAuditFieldCompleteness`;
  - `DataAuditGrantSample`;
  - `DataAuditSourceRow`;
  - `GrantRepository.data_audit_report`;
  - deterministic weak/noise audit helpers.
- `grant_tool/cli.py`:
  - команда `data-audit`;
  - formatter `_format_data_audit_report`.
- `tests/test_data_preparation_audit.py`:
  - tests для source counts;
  - field completeness;
  - weak records;
  - noise candidates;
  - CLI formatting.

Архітектурне рішення:

- schema не змінювалась;
- `quality_score`, `quality_flags`, `classification` і duplicate tables не додавались на Step 1;
- audit використовує тільки наявні normalized поля і source/manual-review сигнали;
- це підготовчий шар для Step 2 quality contract.

Acceptance:

- audit запускається локально через CLI;
- audit показує статистику по source;
- audit показує field completeness;
- audit показує manual review ratio;
- audit показує weak records і noise candidates;
- Step 1 перенесено з `plan_for_data.md` у цей файл.

Перевірка:

```text
poetry run python -m unittest tests.test_data_preparation_audit tests.test_stage5_extraction
poetry run python -m compileall grant_tool tests
```

Docker/live validation:

```text
docker compose up -d
docker compose build app
docker compose up -d --force-recreate app
curl -s -i http://localhost:8000/api/v1/health
docker compose exec app grant-tool data-audit --sample-limit 1
docker compose exec app grant-tool data-audit --source nipo --sample-limit 2
docker compose exec app python -m unittest
docker compose exec app python -m compileall grant_tool tests
```

Live audit result on the current local Postgres dataset:

- total grants: `419`;
- manual review: `275/419 (65.6%)`;
- weak records: `419/419 (100.0%)`;
- noise candidates: `236/419 (56.3%)`;
- highest immediate cleanup targets by observed audit output:
  - missing normalized fields: `funder_name`, `regions`, `application_url`, `published_at`;
  - noisy sources by ratio/count: `nipo`, `prostir`, `hromady`;
  - empty source in current dataset: `gurt`.

Container verification result:

- API health returned `HTTP/1.1 200 OK`;
- full container test suite returned `Ran 69 tests ... OK`;
- container compileall completed successfully.

### Step 2: Define Grant Quality Contract

Статус: реалізовано.

Дата реалізації: `2026-06-02`.

Мета Step 2 була перетворити результати Step 1 audit у app-facing contract, який можна використовувати для dashboard, matching gate, manual review і майбутнього quality score.

Реалізовано:

- окремий документ contract:
  - `docs/plan/data/grant_quality_contract.md`;
- code-level data quality package:
  - `grant_tool/data_quality/__init__.py`;
  - `grant_tool/data_quality/contract.py`;
- unit tests:
  - `tests/test_data_quality_contract.py`.

Contract визначає:

- allowed statuses:
  - `open`;
  - `closed`;
  - `unknown`;
- quality tiers:
  - `match_ready`;
  - `usable_with_warnings`;
  - `needs_review`;
  - `noise_rejected`;
- classification values:
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
  - `unknown`;
- core, important optional і advanced/enrichment fields;
- quality flags;
- manual review rules;
- source families;
- active matching gate rules.

Code-level evaluator:

```python
from grant_tool.data_quality import evaluate_grant_quality_contract

evaluation = evaluate_grant_quality_contract(grant)
```

Evaluator повертає:

- `tier`;
- `classification`;
- `flags`;
- `manual_review_rules`;
- `matching_eligible`;
- `matching_blockers`;
- `source_family`;
- `core_complete`;
- `important_missing_fields`.

Архітектурне рішення:

- schema не змінювалась;
- `quality_score` і persisted `quality_flags` не додавались на Step 2;
- matching behavior ще не переписувався;
- full deterministic title/content noise classification було залишено для Step 3 і реалізовано нижче;
- contract є pure read-only layer поверх існуючої `Grant` model.

Acceptance:

- quality contract описаний у документації;
- contract можна використати в коді;
- поля розділені на core, important optional і advanced/enrichment;
- app-facing quality tiers визначені;
- matching gate визначений;
- є список allowed statuses;
- є список quality flags;
- є список classification values;
- є правила для manual review;
- behavior покритий tests.

Перевірка:

```text
poetry run python -m unittest tests.test_data_quality_contract
poetry run python -m unittest tests.test_data_quality_contract tests.test_data_preparation_audit tests.test_stage6_matching
poetry run python -m unittest
poetry run python -m compileall grant_tool tests
docker compose exec app python -c "from grant_tool.data_quality import GrantQualityTier; print(GrantQualityTier.MATCH_READY.value)"
```

Verification result:

- targeted contract tests returned `Ran 7 tests ... OK`;
- targeted contract/audit/matching tests returned `Ran 12 tests ... OK`;
- full local suite returned `Ran 76 tests ... OK`;
- compileall completed successfully;
- running Docker app can import `grant_tool.data_quality`.

### Step 3: Noise Classification And Matching Gate

Статус: реалізовано.

Дата реалізації: `2026-06-02`.

Мета Step 3 була рано відокремити справжні grant/support opportunities від news/digest/webinar/event/article/training/tender noise і не допускати такі records у active matching.

Реалізовано:

- deterministic text classification у `grant_tool/data_quality/contract.py`;
- source-specific uncertainty gate для digest-heavy, aggregator і empty/problem source families;
- `classification_reasons` у `GrantQualityEvaluation`;
- новий quality flag:
  - `source_classification_uncertain`;
- нове manual review rule:
  - `source_classification_uncertain`;
- matching hard filter integration у `grant_tool/matching/service.py`;
- quality evidence у `MatchCandidate.evidence["quality"]`;
- tests для deterministic noise classification і matching gate.

Класифікація тепер враховує:

- explicit source/extraction fields:
  - `extraction_metadata.classification`;
  - `source_metadata.classification`;
  - `opportunity_type`;
  - `support_type`;
- deterministic title/content markers для:
  - direct grant calls;
  - digest;
  - news;
  - article;
  - event;
  - webinar;
  - training;
  - tender;
  - finance program;
  - structured opportunity.

Matching gate behavior:

- `noise_rejected` records отримують hard filter reason:
  - `quality_gate:noise_rejected:<classification>`;
- `needs_review` records отримують hard filter reason:
  - `quality_gate:needs_review`;
- quality blockers додаються як:
  - `quality_gate:<blocker>`;
- `usable_with_warnings` records не блокуються, але warnings додаються в `manual_checks`;
- raw records не видаляються і не змінюються.

Source-specific behavior:

- direct grant wording wins over generic noisy source risk;
- digest-heavy/aggregator sources з unknown classification і без direct grant signal переходять у `needs_review`;
- useful incomplete sources можуть лишатися `usable_with_warnings`, якщо мають достатній context.

Архітектурне рішення:

- schema не змінювалась;
- persisted `quality_flags`, `quality_score` і prepared table не додавались;
- gate підключений у matching layer, а не в repository query, щоб evaluated/filtered counts лишались прозорими;
- old raw/normalized records не видаляються.

Acceptance:

- noisy records не потрапляють у matching без flag/tier;
- classification пояснювана через `classification_reasons`, flags і matching evidence;
- є tests для digest/news/webinar/article/event/training cases;
- source-specific behavior покритий tests;
- зміни не ламають ingestion;
- raw records не видаляються.

Перевірка:

```text
poetry run python -m unittest tests.test_data_quality_contract tests.test_stage6_matching
poetry run python -m unittest tests.test_data_quality_contract tests.test_data_preparation_audit tests.test_stage6_matching tests.test_stage5_extraction
poetry run python -m unittest
poetry run python -m compileall grant_tool tests
docker compose exec app python -c "from grant_tool.data_quality import GrantClassification, GrantQualityTier; print(GrantClassification.WEBINAR.value, GrantQualityTier.NOISE_REJECTED.value)"
```

Verification result:

- targeted Step 3 contract/matching tests returned `Ran 14 tests ... OK`;
- broader data quality/audit/matching/extraction tests returned `Ran 35 tests ... OK`;
- full local suite returned `Ran 80 tests ... OK`;
- compileall completed successfully;
- running Docker app can import the new classification/gate symbols.

### Step 4: Normalize Critical Fields

Статус: реалізовано.

Дата реалізації: `2026-06-02`.

Мета Step 4 була привести critical normalized fields у `grants` до стабільного формату для records, які не відкидаються раннім noise gate.

Реалізовано deterministic normalization layer:

- `grant_tool/data_quality/normalization.py`;
- exports у `grant_tool/data_quality/__init__.py`;
- integration у `grant_tool/extraction/service.py`;
- currency/amount extraction aliases у `grant_tool/ingestion/utils.py`.

Нормалізовані поля:

- `status` до `open`, `closed`, `unknown`;
- `deadline_at` і `deadline_text`;
- `funding_amount_text`;
- `currency`;
- `countries`;
- `regions`;
- `funder_name`;
- `support_type`;
- `opportunity_type`;
- `eligibility_text`.

Ключові правила:

- deadline parser використовує існуючі deterministic date helpers і чистить UI-tail noise типу Google calendar/share/detail;
- currency extraction підтримує `EUR`, `USD`, `UAH`, `GBP`, `PLN`, `CAD` та поширені українські/символьні aliases;
- `C$` обробляється як `CAD`, а не як generic `USD`;
- amount text чиститься від JSON budget blobs, дат і prefix noise, але raw value лишається, якщо валюта непевна;
- source-level funder fallback застосовується тільки для джерел із зрозумілим власником, наприклад `eu-funding` і `diia-business`;
- funder може бути витягнутий з короткого parenthetical title evidence, наприклад `(ACTED)`;
- country/region inference додає базову Україну, EU і українські області за text evidence;
- support type inference мапить training/tender/loan/guarantee/leasing/voucher/compensation/finance programme/grant на стабільні values;
- weak amount records без надійної валюти отримують manual review reason через `NormalizationResult.review_reasons`;
- normalization записує `normalization_rule_version` і `normalized_fields` у `extraction_metadata`.

Архітектурне рішення:

- schema не змінювалась;
- normalization підключена в Stage 5 enrichment після deterministic extraction і повторно після optional LLM extraction;
- normalization не вводить global hard requirement для `funder_name`, `regions`, `application_url`, `published_at`;
- raw records не видаляються;
- непевні значення не перезаписуються вигаданими даними.

Acceptance:

- нормалізація покрита unit tests;
- Stage 5 integration test підтверджує, що normalization застосовується під час enrichment;
- ingestion flow не зламаний;
- raw amount value не губиться, якщо currency непевна;
- weak amount records можуть отримувати manual review reason;
- global hard requirement для optional source-dependent fields не доданий.

Перевірка:

```text
poetry run python -m unittest tests.test_data_normalization
poetry run python -m unittest tests.test_stage5_extraction
poetry run python -m unittest
poetry run python -m compileall grant_tool tests
docker compose build app
docker compose up -d app
docker compose exec app python -m unittest tests.test_data_normalization tests.test_stage5_extraction
curl -s -i http://localhost:8000/api/v1/health
```

Verification result:

- targeted normalization tests returned `Ran 6 tests ... OK`;
- targeted Stage 5 extraction tests returned `Ran 21 tests ... OK`;
- full local suite returned `Ran 88 tests ... OK`;
- compileall completed successfully;
- Docker app image rebuilt and app service restarted successfully;
- Docker targeted normalization/extraction tests returned `Ran 27 tests ... OK`;
- Docker API health returned `HTTP/1.1 200 OK`.

### Step 5: Deduplication

Статус: реалізовано.

Дата реалізації: `2026-06-03`.

Мета Step 5 була знайти duplicate candidates між джерелами і всередині одного джерела без видалення records і без втрати trace.

Реалізовано soft-dedup layer:

- `grant_tool/deduplication/service.py`;
- `grant_tool/deduplication/__init__.py`;
- repository query:
  - `GrantRepository.list_grants_for_deduplication`;
- CLI command:
  - `grant-tool deduplicate`;
  - `grant-tool deduplicate --dry-run`;
- quality flag integration:
  - `QualityFlag.POSSIBLE_DUPLICATE`;
- matching gate integration:
  - non-primary duplicates отримують hard filter `duplicate_grant:<primary_grant_id>`.

Duplicate detector:

- порівнює canonical `source_url` і `application_url`;
- нормалізує title і рахує exact/fuzzy title similarity;
- враховує deadline;
- враховує funder;
- враховує program name;
- враховує funding amount/currency;
- враховує taxonomy overlap;
- має source-pair rule для `eu-funding` і `eufundingportal-eu`;
- використовує окремі thresholds:
  - candidate threshold;
  - duplicate group threshold.

Metadata format:

```text
grant.extraction_metadata["deduplication"] = {
  version,
  is_duplicate,
  is_primary,
  potential_duplicate,
  duplicate_group_id,
  duplicate_group_size,
  primary_grant_id,
  max_candidate_score,
  candidate_count,
  candidates
}
```

Primary record rule:

- prefer higher quality tier;
- prefer structured/direct source over aggregator/digest-heavy source;
- prefer `open` over `unknown`/`closed`;
- prefer richer structured fields;
- prefer higher extraction confidence;
- prefer richer context text;
- tie-break deterministically by update time and grant id.

Архітектурне рішення:

- schema не змінювалась;
- duplicate groups не винесені в окрему таблицю на Step 5;
- duplicates не видаляються;
- primary/non-primary status зберігається в `extraction_metadata`;
- matching пропускає primary record і фільтрує non-primary duplicate records;
- окрема duplicate table або prepared view лишається можливістю для Step 8, якщо буде потрібен більш формальний prepared layer.

Acceptance:

- duplicate candidates не видаляються без trace;
- candidates можна перевірити через `grant-tool deduplicate --dry-run`;
- exact duplicate cases покриті tests;
- fuzzy duplicate cases покриті tests;
- matching layer може ігнорувати non-primary duplicates;
- quality contract бачить duplicate risk як `possible_duplicate`.

Перевірка:

```text
poetry run python -m unittest tests.test_data_deduplication
poetry run python -m unittest tests.test_data_deduplication tests.test_stage6_matching tests.test_stage8_search_report
poetry run python -m unittest
poetry run python -m compileall grant_tool tests
docker compose exec app grant-tool deduplicate --dry-run
docker compose exec app python -m unittest tests.test_data_deduplication tests.test_stage6_matching tests.test_stage8_search_report
curl -s -i http://localhost:8000/api/v1/health
```

Verification result:

- targeted deduplication tests returned `Ran 2 tests ... OK`;
- deduplication/matching/CLI formatter tests returned `Ran 10 tests ... OK`;
- full local suite returned `Ran 91 tests ... OK`;
- compileall completed successfully;
- Docker app image rebuilt and app service restarted successfully;
- Docker targeted deduplication/matching/CLI formatter tests returned `Ran 10 tests ... OK`;
- Docker API health returned `HTTP/1.1 200 OK`;
- Docker dry-run returned `processed=419 candidates=0 duplicate_pairs=0 duplicate_groups=0 duplicate_records=0 dry_run=yes`.

### Step 6: AI Fallback For Extraction

Статус: реалізовано.

Дата реалізації: `2026-06-03`.

Мета Step 6 була зробити AI extraction контрольованим fallback, а не першим шаром extraction.

Реалізовано в `grant_tool/extraction/service.py`:

- fallback policy:
  - AI викликається тільки коли deterministic extraction лишає weak/missing fields;
  - AI не викликається, якщо deterministic extraction достатній;
  - AI не викликається, якщо source text занадто короткий;
- prompt contract для OpenAI client;
- schema validation для AI result;
- confidence gate;
- traceable metadata:
  - `extraction_metadata["llm"]["version"]`;
  - `status`;
  - `fallback_reasons`;
  - `schema_errors`;
  - `confidence`;
  - `applied_fields`;
  - sanitized `output`;
- no-key fallback behavior:
  - якщо `--use-llm` увімкнено, але `OPENAI_API_KEY` немає, record не падає;
  - metadata отримує `status=skipped`;
  - ambiguous record отримує manual review reason;
- safe merge rules:
  - text fields заповнюються тільки коли вони missing або weak;
  - deterministic summary не перезаписується якісним AI summary;
  - list fields merge-яться без видалення deterministic values;
  - classification може бути записана в metadata тільки якщо нема existing classification і AI value проходить schema.

AI fallback може допомагати з:

- `summary`;
- `eligibility_text`;
- `restrictions_text`;
- `applicant_types`;
- `topics`;
- `countries`;
- `regions`;
- `classification`.

Schema contract:

```text
{
  summary: string|null,
  eligibility_text: string|null,
  restrictions_text: string|null,
  applicant_types: string[],
  topics: string[],
  countries: string[],
  regions: string[],
  classification: allowed classification value,
  confidence: number between 0 and 1,
  evidence: object
}
```

Архітектурне рішення:

- AI output не записується в raw fields/source payload;
- AI output зберігається окремо в `extraction_metadata["llm"]`;
- invalid/low-confidence AI result не merge-иться в normalized fields;
- failed AI call не валить весь feature extraction job;
- `--use-llm` лишається explicit opt-in switch.

Acceptance:

- AI не перезаписує deterministic fields без правила;
- AI output traceable;
- є fallback behavior без API key;
- є tests для schema validation;
- manual review reason пояснює AI uncertainty.

Перевірка:

```text
poetry run python -m unittest tests.test_stage5_extraction
poetry run python -m unittest
poetry run python -m compileall grant_tool tests
docker compose exec app python -m unittest tests.test_stage5_extraction
curl -s -i http://localhost:8000/api/v1/health
```

Verification result:

- targeted Stage 5 extraction tests returned `Ran 25 tests ... OK`;
- full local suite returned `Ran 95 tests ... OK`;
- compileall completed successfully.
- Docker app image rebuilt and app service restarted successfully;
- Docker targeted Stage 5 extraction tests returned `Ran 25 tests ... OK`;
- Docker API health returned `HTTP/1.1 200 OK`.

### Step 7: Quality Score

Статус: реалізовано.

Дата реалізації: `2026-06-10`.

Дата Docker/live validation: `2026-06-10`.

Мета Step 7 була додати вимірювану, deterministic якість кожного grant record і не пускати слабкі records у matching без явного дозволу.

Реалізовано:

- persisted поля в `grants`:
  - `quality_score` (`0-100`, integer);
  - `quality_tier` (contract tier value);
  - `quality_flags` (JSON list contract flag values);
- explainable breakdown в `extraction_metadata["quality"]`:
  - `version`, `score`, `tier`, `classification`, `flags`, `components`, `penalties`, `matching_ready`, `min_matching_quality_score`;
- pure scoring layer:
  - `grant_tool/data_quality/scoring.py`:
    - `compute_grant_quality_score`;
    - `apply_grant_quality_score`;
    - `QUALITY_SCORING_VERSION = "data-preparation-step7-v1"`;
    - `DEFAULT_MIN_MATCHING_QUALITY_SCORE = 40`;
- scoring service з JobRun audit:
  - `grant_tool/data_quality/service.py` (`QualityScoringService`, `JobType.QUALITY_SCORE`);
- CLI:
  - `grant-tool quality-score`;
  - `grant-tool quality-score --dry-run`;
  - `grant-tool quality-score --source <slug> --limit N --min-score N`;
- автоматичне оновлення persisted score:
  - після Stage 5 `extract-features` (per-grant після `update_grant_features`);
  - після `deduplicate` (бо duplicate flags впливають на score);
- matching gate:
  - hard filter `quality_gate:low_quality_score:<score>` для records з persisted score нижче порога;
  - `grant-tool match --include-low-quality` як явний дозвіл;
  - `grant-tool match --min-quality-score N` для зміни порога;
  - matching evidence містить `persisted_score` і `persisted_tier`;
- Alembic migration `20260610_0005` з робочим downgrade;
- tests: `tests/test_data_quality_score.py`.

Формула score (deterministic, компоненти сумуються до 100):

- core fields: 40 (title 10, source_url 10, context text 10, valid status 10);
- important optional fields: 30 (deadline 8, funder 4, amount 4, currency 2, country 4, region 1, eligibility 4, application_url 2, published_at 1);
- advanced fields як слабкий сигнал: max 5 (program_name, keywords, restrictions_text, funding_amount_max, documents);
- text richness: 10 (summary >= 80 chars 5, description >= 300 chars 5);
- status: open 5, unknown 2, closed 0;
- source family: structured_direct 10, useful_incomplete 7, unknown 5, aggregator 4, digest_heavy 2, empty_or_problem 0.

Penalties:

- noise classification: 60;
- needs_manual_review: 15;
- source_classification_uncertain: 10;
- low_extraction_confidence: 10;
- possible_duplicate: 10;
- broad_finance_program: 5.

Acceptance:

- score deterministic (покрито tests);
- flags explainable (persisted значення contract flags, breakdown у metadata);
- є CLI/report для перегляду score по source і tier;
- records з низьким score не використовуються в matching без явного дозволу (`--include-low-quality`).

Перевірка:

```text
poetry run python -m unittest
docker compose exec app alembic upgrade head
docker compose exec app alembic downgrade 20260522_0004 && docker compose exec app alembic upgrade head
docker compose exec app grant-tool quality-score --dry-run
docker compose exec app grant-tool quality-score
docker compose exec app grant-tool deduplicate
docker compose exec app grant-tool match --top-n 5 --min-score 0.20 --use-vector
docker compose exec app python -m unittest
curl -s -i http://localhost:8000/api/v1/health
```

Live result на поточному локальному dataset (419 grants):

- `processed=419 avg=57.6 low_score(<40)=14 matching_ready=128`;
- tiers: `needs_review=266 usable_with_warnings=139 noise_rejected=14`;
- migration upgrade/downgrade roundtrip пройшов на Postgres;
- повний container test suite: `Ran 104 tests ... OK`;
- API health: `200`.

### Step 8: Prepared Grants Layer

Статус: реалізовано.

Дата реалізації: `2026-06-10`.

Мета Step 8 була дати зрозумілий prepared шар даних для matching, dashboard і AI-рекомендацій.

Задокументоване архітектурне рішення:

- окрема таблиця `prepared_grants`, materialized view або SQL view НЕ створюються;
- prepared layer = persisted quality fields у `grants` (`quality_score`, `quality_tier`, `quality_flags`) плюс query layer;
- причина: дані вже нормалізовані в `grants`, dedup/score metadata зберігаються поряд із record, а окрема таблиця додала б синхронізаційний ризик без нової інформації;
- якщо в майбутньому потрібен буде окремий serving layer, рішення можна переглянути після появи реального performance вимірювання.

Реалізовано:

- repository prepared set:
  - `GrantRepository.list_prepared_grants(min_quality_score, include_unscored, limit)`;
  - prepared tiers: `match_ready`, `usable_with_warnings`;
  - unscored records (tier `NULL`) включаються за замовчуванням, щоб шар деградував м'яко до першого quality-score run;
- dashboard quality state:
  - stats: `grants_prepared`, `grants_noise`, `grants_unscored`, `quality_tier_counts`;
  - overview: metric "Prepared for matching" і tier distribution;
  - grants page: quality filter (`prepared`, `match_ready`, `usable_with_warnings`, `needs_review`, `noise_rejected`, `unscored`), score/tier на card і `noise` tag;
- matching використовує live contract evaluation плюс persisted score gate (Step 7), тому noise/low-score records не потрапляють у matching set без explicit override;
- tests: prepared set у `tests/test_data_quality_score.py`, dashboard quality state у `tests/test_stage9_dashboard.py`.

Acceptance:

- є зрозумілий prepared set для matching (`list_prepared_grants` + score gate);
- dashboard показує quality state;
- manual review records видно окремо (existing manual review filter + needs_review tier);
- non-grant/noise records не змішуються з якісними grants (tier filter, noise tag, окремий лічильник);
- рішення про table/view/fields задокументоване в цьому файлі та в `grant_quality_contract.md`.

### Ревізія Полів БД: Видалення Overengineered Fields

Статус: реалізовано.

Дата реалізації: `2026-06-10`.

Мета: прибрати поля, які писались, але ніколи не читались жодним app-шляхом (overengineering), і спростити схему без втрати raw/audit даних.

Видалені поля (написані, ніколи не читались):

- `grants.language`;
- `grants.opens_at`;
- `grants.extraction_method` (повна інформація лишається в `extraction_metadata.fields[*].method` і `extraction_metadata.llm.status`);
- `grants.cofinancing_required`, `grants.consortium_required` (булеві дублікати наявності `cofinancing_text`/`consortium_text`, які лишаються і використовуються embeddings);
- `grants.implementation_period_text`, `grants.contact_text`;
- `sources.requires_browser` (дублює `access_strategy`);
- `client_profiles.source_type`, `client_profiles.source_uri` (provenance лишається в `profile_metadata`);
- `match_runs.run_type` (константа без читачів);
- таблиця `reports` повністю (писалась тільки тестами; `/report` page рендериться з live data) разом із `JobType.REPORT` (замінений на `JobType.QUALITY_SCORE`).

Свідомо збережені поля:

- всі raw snapshot поля (`raw_title`, `raw_summary`, `raw_text`, `raw_html`, `raw_payload`, `snapshot_metadata`) - raw/audit layer;
- `profile_metadata`, `history_metadata`, `match_runs.parameters`, `match_runs.notes`, `sources.notes` - audit/provenance;
- `geography_text`, `documents`, `funding_amount_min/max`, `cofinancing_text`, `consortium_text` - реально читаються quality contract, audit, dedup або embeddings.

Migration: `migrations/versions/20260610_0005_quality_score_and_field_cleanup.py` (upgrade + повний downgrade).

Документація оновлена: `docs/fields.md`, `docs/implemented_mvp.md`, `docs/operations.md`, `docs/plan/data/grant_quality_contract.md`, `CLAUDE.md`.
