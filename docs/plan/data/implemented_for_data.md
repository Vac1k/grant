# Виконано Для Підготовки Даних Грантів

## Призначення Файлу

Цей файл є єдиним місцем, куди переноситься все, що вже реалізовано для етапу підготовки даних грантів.

Правило роботи з файлами:

- `plan_for_data.md` містить те, що ще треба зробити;
- `implemented_for_data.md` містить тільки те, що вже реалізовано і перевірено;
- після кожного наступного prompt-а виконаний пункт або підпункт переноситься з `plan_for_data.md` у цей файл;
- пункт не переноситься сюди, якщо він тільки обговорений, але ще не реалізований або не перевірений.

## Поточний Статус Етапу Data Preparation

Етап підготовки даних грантів ще не завершений.

Фактичний стан:

- Stage Search / Link Extraction завершений;
- дані вже потрапляють у `discovered_grant_items`, `raw_grant_snapshots` і `grants`;
- Step 1 audit поточного стану таблиці `grants` реалізований як read-only CLI/report;
- Step 2 quality contract реалізований як документація і pure code-level evaluator;
- наступний відкритий крок - `Step 3: Noise Classification And Matching Gate`.

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
- full deterministic title/content noise classification лишається для Step 3;
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
