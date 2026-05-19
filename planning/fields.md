# Аналіз полів для MVP-джерел

## Мета

Перед Stage 2 треба уточнити, які поля реально варто робити колонками в database, а які краще зберігати як raw/JSON або витягувати через LLM.

MVP-джерела:

- EU Funding & Tenders Portal
- Prostir grants
- GURT grants
- Diia Business finance programs

## Висновок

Не треба робити всі бажані grant fields обов'язковими колонками.

Правильний підхід для Stage 2:

- стабільні поля зберігати як нормальні database columns;
- нестабільні source-specific поля зберігати в `source_metadata` / `raw_payload` JSON;
- складні поля витягувати пізніше через deterministic parsing + LLM;
- raw snapshot зберігати завжди, навіть якщо normalized extraction неповний.

## Що видно по джерелах

### EU Funding & Tenders Portal

EU Portal має багато структурних metadata, але вони вкладені й залежать від типу opportunity.

Реально доступні або корисні поля:

- identifier / reference / topic id
- title
- status
- call identifier
- call title
- framework programme
- types of action
- keywords
- topic description
- planned opening date
- deadline dates
- deadline model
- budget overview
- programme division
- additional information / documents
- source JSON URL

Висновок:

- EU дає найкраще структуровані дані.
- Але budget/deadline/action часто лежать у вкладених JSON структурах.
- Потрібен `source_metadata` JSON, навіть якщо частину полів нормалізуємо в колонки.

### Prostir

Prostir category page дає стабільні list-level поля:

- title
- source URL
- date range, наприклад publication date + deadline
- excerpt
- category/page type

Detail page часто дає:

- актуально до / deadline
- full text
- хто може подати заявку
- geography
- amount
- restrictions
- documents
- contact email / application instructions

Висновок:

- Prostir має корисну date/deadline структуру на listing і detail pages.
- Applicant type, geography, amount і restrictions часто є в тексті, але не як стабільні machine fields.
- Для Prostir треба зберігати full text і робити extraction.

### GURT

GURT listing дає:

- title
- publication date
- short excerpt
- source URL

Detail page може містити:

- full text
- deadline
- amount
- funder
- eligibility
- tags
- application instructions
- linked documents

Висновок:

- GURT менш структурований, ніж Prostir.
- Deadline/amount/funder часто є в тексті.
- Для GURT normalized fields мають бути optional, а full text важливий.

### Diia Business finance programs

Diia Business detail pages мають більш стабільні sections:

- provider / institution
- title
- help type
- amount
- currency
- programme end date / deadline
- target purpose
- for whom
- conditions
- additional conditions
- funding programme
- external apply/source URL
- similar programmes

Висновок:

- Diia Business добре підходить для deterministic extraction.
- Треба розрізняти business finance programme, grant, loan, regional programme, deposit, leasing.
- Поле має називатись не тільки `grant_type`, а ширше: `opportunity_type` або `support_type`.

## Рекомендовані core поля для `grants`

Ці поля варто зробити колонками в Stage 2.

- `id`
- `source_id`
- `latest_raw_snapshot_id`
- `source_record_id`
- `source_url`
- `application_url`
- `title`
- `summary`
- `description_text`
- `language`
- `status`
- `published_at`
- `opens_at`
- `deadline_at`
- `deadline_text`
- `program_name`
- `funder_name`
- `opportunity_type`
- `support_type`
- `funding_amount_min`
- `funding_amount_max`
- `funding_amount_text`
- `currency`
- `geography_text`
- `countries`
- `regions`
- `eligibility_text`
- `applicant_types`
- `topics`
- `keywords`
- `restrictions_text`
- `cofinancing_required`
- `cofinancing_text`
- `consortium_required`
- `consortium_text`
- `implementation_period_text`
- `contact_text`
- `documents`
- `source_metadata`
- `extraction_method`
- `extraction_confidence`
- `extraction_metadata`
- `needs_manual_review`
- `manual_review_reason`
- `created_at`
- `updated_at`

## Поля, які не мають бути required

Ці поля важливі, але не можна вимагати їх для кожного grant.

- `deadline_at`
- `funding_amount_min`
- `funding_amount_max`
- `currency`
- `program_name`
- `funder_name`
- `countries`
- `regions`
- `applicant_types`
- `topics`
- `cofinancing_required`
- `consortium_required`

Причина:

- EU має частину цих полів структуровано.
- Diia Business часто має amount/currency/deadline.
- Prostir і GURT часто мають ці дані тільки в тексті.
- Частина українських можливостей не є класичними grants, а може бути training, tender, regional support або finance programme.

## Поля, які краще не робити окремими колонками зараз

- `risks`
- `risk_score`
- `source_specific_category`
- `exact_eu_budget_overview`
- `exact_eu_framework_programme_id`
- `all_related_links_as_columns`
- `all_document_links_as_columns`

Краще:

- factual restrictions/cofinancing/consortium зберігати в grant;
- risks генерувати на рівні match/report;
- source-specific fields зберігати в `source_metadata`;
- document links зберігати в `documents` JSON.

## Raw snapshot fields

Raw data треба зберігати завжди.

Рекомендована модель: `RawGrantSnapshot`.

Поля:

- `id`
- `source_id`
- `source_record_id`
- `source_url`
- `fetched_at`
- `http_status`
- `content_type`
- `raw_title`
- `raw_summary`
- `raw_text`
- `raw_html`
- `raw_payload`
- `content_hash`
- `metadata`

Навіщо:

- deduplication;
- audit trail;
- повторна extraction після зміни логіки;
- відстеження оновлень deadline/status/content.

## Source-specific JSON

У `grants.source_metadata` зберігати те, що не є стабільним між джерелами.

Приклади для EU:

- `identifier`
- `reference`
- `call_identifier`
- `call_title`
- `framework_programme`
- `types_of_action`
- `budget_overview`
- `programme_division`

Приклади для Prostir/GURT:

- `author`
- `category`
- `tags`
- `listing_date_range`
- `original_deadline_text`

Приклади для Diia:

- `provider`
- `help_type`
- `target_purpose`
- `for_whom`
- `conditions`
- `additional_conditions`
- `similar_programmes`

## Extraction metadata

Не треба робити окрему колонку confidence для кожного поля.

Краще мати:

- `extraction_confidence` як загальний score;
- `extraction_metadata` JSON для details.

Приклад:

```json
{
  "fields": {
    "deadline_at": {
      "method": "deterministic",
      "confidence": 0.95,
      "evidence": "Актуально до: 24.05.26"
    },
    "applicant_types": {
      "method": "llm",
      "confidence": 0.78,
      "evidence": "До участі запрошуються місцеві ОГС..."
    }
  }
}
```

## Matching impact

Для matching найважливіші поля:

- `title`
- `summary`
- `description_text`
- `status`
- `deadline_at` або `deadline_text`
- `eligibility_text`
- `applicant_types`
- `topics`
- `geography_text`
- `funding_amount_text`
- `restrictions_text`
- `cofinancing_text`
- `consortium_text`
- `program_name`
- `funder_name`
- `source_url`

Для MVP matching не має падати, якщо частина цих полів відсутня.

## Рекомендація для Stage 2

У Stage 2 реалізувати schema так:

- `grants` має мати стабільні normalized columns;
- list-like fields (`countries`, `regions`, `applicant_types`, `topics`, `keywords`, `documents`) зберігати як JSON;
- source-specific fields зберігати в `source_metadata`;
- extraction details зберігати в `extraction_metadata`;
- raw snapshots зберігати окремо;
- required у database мають бути тільки технічні поля, `source_url`, `title` або fallback raw title.

Мінімальні required normalized fields:

- `source_id`
- `source_url`
- `title`
- `status`
- `created_at`
- `updated_at`

Все інше має бути nullable або мати safe default.

## Додаткова рекомендація для Stage 2.5

`JobRun` не є grant business entity, але потрібен перед Stage 3, щоб ingestion був контрольованим.

Статус реалізації: done. `JobRun` реалізовано окремою migration `20260519_0002_create_job_runs.py`, а MVP source seed запускається автоматично через Docker Compose service `migrate`.

У `job_runs` варто зберігати:

- `id`
- `job_type`
- `source_id`, nullable
- `status`
- `started_at`
- `finished_at`
- `processed_count`
- `created_count`
- `updated_count`
- `skipped_count`
- `failed_count`
- `error_message`
- `job_metadata`

`JobRun` має покривати не тільки scheduled jobs, а й ручні CLI-запуски:

- source seeding;
- ingestion;
- client import;
- application history import;
- matching;
- LLM extraction;
- embedding generation;
- report generation.

Це дозволить Stage 3 connectors повертати зрозумілий результат: що було оброблено, що створено, що оновлено і де сталася помилка.
