# Поля даних у реалізованому MVP

Цей документ описує фактичну структуру полів, яка зараз реалізована в коді.

Основні джерела правди:

- `grant_tool/db/models.py`
- `grant_tool/ingestion/types.py`
- `grant_tool/extraction/service.py`

## Загальний принцип

Система розділяє дані на два рівні:

1. Raw data - оригінальні дані з сайту або API.
2. Normalized data - очищені поля, які використовуються для dashboard, matching, embeddings і explanations.

Raw data зберігається у `raw_grant_snapshots`.

Normalized grants зберігаються у `grants`.

## MVP-Джерела

Поточні джерела:

- EU Funding & Tenders Portal
- Prostir
- Diia Business
- GURT

Кожне джерело має різну якість структури, тому більшість business fields у `grants` є nullable або мають safe default.

Обов'язковий мінімум для grant:

- `source_id`
- `source_url`
- `title`
- `status`

## `sources`

Таблиця: `sources`

Призначення: описує зовнішнє джерело грантів і спосіб доступу до нього.

Поля:

- `id`
- `created_at`
- `updated_at`
- `name`
- `slug`
- `base_url`
- `list_url`
- `api_url`
- `feed_url`
- `sitemap_url`
- `access_strategy`
- `requires_browser`
- `enabled`
- `rate_limit_seconds`
- `notes`
- `source_metadata`

`access_strategy` може бути:

- `api`
- `wp_rest`
- `rss`
- `sitemap_html`
- `html`
- `browser`
- `manual`

Поточні seeded sources:

- `eu-funding`
- `prostir`
- `diia-business`
- `gurt`

## `raw_grant_snapshots`

Таблиця: `raw_grant_snapshots`

Призначення: зберігає оригінальний snapshot даних, отриманих із джерела.

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

У SQLAlchemy поле називається `snapshot_metadata`, але в базі воно зберігається як колонка `metadata`.

Для API-джерел основне поле:

- `raw_payload`

Для HTML/RSS-джерел основні поля:

- `raw_html`
- `raw_text`
- `raw_title`
- `raw_summary`

Deduplication для raw snapshots базується на:

- `source_id`
- `source_url`
- `content_hash`

## `grants`

Таблиця: `grants`

Призначення: основна normalized таблиця грантів і фінансових можливостей.

### Identity І Source Fields

- `id`
- `created_at`
- `updated_at`
- `source_id`
- `latest_raw_snapshot_id`
- `source_record_id`
- `source_url`
- `application_url`

`source_url` - сторінка або canonical URL можливості.

`application_url` - URL для подачі, якщо він відрізняється від `source_url`.

### Basic Content Fields

- `title`
- `summary`
- `description_text`
- `language`
- `status`

`title` і `status` є required.

`description_text` зазвичай містить очищений повний текст сторінки або опис із API.

### Date Fields

- `published_at`
- `opens_at`
- `deadline_at`
- `deadline_text`

`deadline_at` може бути `NULL`, якщо дедлайн не знайдено або програма відкрита без чіткої дати.

`deadline_text` зберігає оригінальний текстовий фрагмент, якщо дата була знайдена з тексту.

### Program And Funder Fields

- `program_name`
- `funder_name`

Для EU Funding це може бути framework/programme.

Для Diia Business це може бути category або company/provider.

Для Prostir/GURT ці поля часто відсутні або витягуються з тексту.

### Opportunity Type Fields

- `opportunity_type`
- `support_type`

`opportunity_type` описує загальний тип можливості.

Приклади:

- `grant`
- `business_support`
- `training`
- `tender`

`support_type` описує конкретніший тип підтримки.

Приклади:

- `grant`
- `finance_programme`
- `loan`
- `guarantee`
- `leasing`
- `factoring`
- `tender_support`

Diia Business може містити не тільки класичні grants, тому `support_type` важливий для відділення grants від інших finance programmes.

### Funding Fields

- `funding_amount_min`
- `funding_amount_max`
- `funding_amount_text`
- `currency`

`funding_amount_text` зберігає людський текст суми.

`funding_amount_min` і `funding_amount_max` заповнюються тільки якщо суму можна достатньо надійно розпарсити.

Cleanup logic не приймає як funding:

- EU reference/topic IDs;
- роки дедлайнів;
- Diia KVED/classification values типу `01.2`.

### Geography Fields

- `geography_text`
- `countries`
- `regions`

`countries` і `regions` зберігаються як JSON lists.

У matching country mismatch може бути hard filter, якщо grant countries і client country чітко відомі.

### Eligibility And Taxonomy Fields

- `eligibility_text`
- `applicant_types`
- `topics`
- `keywords`

`applicant_types` зберігається як JSON list.

Поточні deterministic applicant type labels:

- `SME`
- `startup`
- `company`
- `NGO`
- `consortium`

`topics` зберігається як JSON list.

Поточні deterministic topic labels:

- `AI`
- `defence`
- `dual-use`
- `innovation`
- `community`
- `business support`
- `education`
- `culture`
- `humanitarian`

`keywords` зараз доповнюються topics і source keywords, якщо вони доступні.

### Restriction And Requirement Fields

- `restrictions_text`
- `cofinancing_required`
- `cofinancing_text`
- `consortium_required`
- `consortium_text`
- `implementation_period_text`
- `contact_text`

Ці поля можуть бути `NULL`, бо більшість джерел не дає їх як структуровані поля.

Deterministic extraction шукає текстові фрагменти з evidence, а не гарантує повну юридичну інтерпретацію.

### Documents And Metadata

- `documents`
- `source_metadata`
- `extraction_method`
- `extraction_confidence`
- `extraction_metadata`
- `needs_manual_review`
- `manual_review_reason`

`documents` - JSON list документів.

Приклад item:

```json
{
  "title": "Guidelines",
  "url": "https://example.org/file.pdf"
}
```

`source_metadata` містить source-specific дані, які не варто робити окремими колонками.

`extraction_metadata` містить технічні деталі extraction:

- `stage`
- `normalization_version`
- `source_slug`
- `fields`
- `feature_card`
- `llm`, якщо LLM extraction запускалась

Поточна normalization version:

```text
stage5-deterministic-v2
```

`needs_manual_review` ставиться, якщо:

- title виглядає generic;
- extracted text дуже короткий;
- не знайдено topics і applicant types;
- extraction confidence або fields потребують людської перевірки.

### Embedding Fields

- `embedding`
- `embedding_text`
- `embedding_model`
- `embedded_at`

`embedding` має dimension `1536`.

Ці поля додані Stage 7 і використовуються для vector similarity.

## `NormalizedGrantDraft`

Клас: `grant_tool/ingestion/types.py`

`NormalizedGrantDraft` є проміжним форматом між connector і таблицею `grants`.

Поля `NormalizedGrantDraft` майже напряму відповідають полям `grants`, крім:

- `source_url`
- `title`
- `status`
- `source_record_id`

Метод `to_grant_fields()` повертає словник полів, які передаються в `repository.upsert_grant(...)`.

Поля draft:

- `source_url`
- `title`
- `status`
- `source_record_id`
- `application_url`
- `summary`
- `description_text`
- `language`
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

## `client_profiles`

Таблиця: `client_profiles`

Призначення: описує клієнта або компанію, для якої шукаються релевантні гранти.

Поля:

- `id`
- `created_at`
- `updated_at`
- `name`
- `slug`
- `country`
- `sector`
- `organization_type`
- `technologies`
- `product_description`
- `risks`
- `target_topics`
- `excluded_topics`
- `previous_submissions_summary`
- `source_type`
- `source_uri`
- `profile_metadata`
- `enabled`
- `embedding`
- `embedding_text`
- `embedding_model`
- `embedded_at`

List-like fields зберігаються як JSON:

- `technologies`
- `target_topics`
- `excluded_topics`

Client profiles імпортуються з:

```text
data/manual_seed/client_profiles.manual.csv
```

## `application_history`

Таблиця: `application_history`

Призначення: зберігає попередні заявки клієнтів на гранти або програми.

Поля:

- `id`
- `created_at`
- `updated_at`
- `client_profile_id`
- `grant_id`
- `client_name`
- `grant_title`
- `grant_source`
- `program_name`
- `application_date`
- `result`
- `country`
- `applicant_type`
- `topics`
- `project_summary`
- `reusable_materials`
- `similarity_weight`
- `notes`
- `history_metadata`
- `embedding`
- `embedding_text`
- `embedding_model`
- `embedded_at`

Allowed `result` values у seed data:

- `won`
- `lost`
- `rejected`
- `not_submitted`
- `unknown`

Попередні заявки є позитивним relevance signal.

`lost`, `rejected` і `not_submitted` не зменшують fit score.

Application history імпортується з:

```text
data/manual_seed/application_history.manual.csv
```

## `job_runs`

Таблиця: `job_runs`

Призначення: audit trail для запусків CLI/job operations.

Поля:

- `id`
- `created_at`
- `updated_at`
- `job_type`
- `source_id`
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

`job_type` може бути:

- `ingestion`
- `import_clients`
- `import_history`
- `feature_extraction`
- `matching`
- `llm_extraction`
- `embedding`
- `seed_sources`

`status` може бути:

- `pending`
- `running`
- `success`
- `failed`
- `partial`

## `match_runs`

Таблиця: `match_runs`

Призначення: один запуск matching.

Поля:

- `id`
- `created_at`
- `updated_at`
- `name`
- `run_type`
- `status`
- `parameters`
- `started_at`
- `completed_at`
- `notes`

`parameters` зберігає:

- `client_slug`
- `grant_limit`
- `top_n`
- `min_score`
- `use_vector`
- `matching_version`

## `grant_client_matches`

Таблиця: `grant_client_matches`

Призначення: конкретний match між grant і client profile.

Поля:

- `id`
- `created_at`
- `updated_at`
- `match_run_id`
- `grant_id`
- `client_profile_id`
- `score`
- `rank`
- `hard_filter_passed`
- `filter_reasons`
- `keyword_score`
- `vector_score`
- `history_score`
- `llm_score`
- `explanation`
- `risks_text`
- `manual_checks`
- `evidence`
- `match_metadata`

`score` - final score після Stage 6/7 logic.

`keyword_score` - deterministic keyword/topic/client fit score.

`vector_score` - semantic similarity score, якщо embeddings існують і `--use-vector` увімкнений.

`history_score` - boost зі схожої application history.

`llm_score` - confidence/quality score для explanation, не заміна final `score`.

`evidence` містить:

- keyword evidence;
- vector evidence;
- history evidence;
- hard filter reasons;
- manual checks.

`match_metadata.score_breakdown` містить:

- `keyword_score`
- `vector_score`
- `history_score`
- `stage6_fallback_score`
- `final_score`

## Поля, Які Не Треба Робити Окремими Колонками

Ці дані краще залишати в JSON або зберігати на рівні matching:

- source-specific categories;
- exact EU internal metadata IDs;
- all related links as separate columns;
- all document links as separate columns;
- parser debug details;
- LLM raw response;
- field-level confidence columns для кожного окремого поля;
- match risks на рівні `grants`.

Куди їх класти:

- source-specific дані -> `source_metadata`;
- raw API/HTML -> `raw_grant_snapshots`;
- extraction details -> `extraction_metadata`;
- documents -> `documents`;
- matching risks -> `grant_client_matches.risks_text`;
- explanation details -> `grant_client_matches.match_metadata`.

## Поля, Які Важливі Для Matching

Найважливіші grant fields:

- `title`
- `summary`
- `description_text`
- `status`
- `deadline_at`
- `deadline_text`
- `countries`
- `geography_text`
- `eligibility_text`
- `applicant_types`
- `topics`
- `keywords`
- `funding_amount_text`
- `restrictions_text`
- `cofinancing_text`
- `consortium_text`
- `program_name`
- `funder_name`
- `opportunity_type`
- `support_type`
- `source_url`

Найважливіші client fields:

- `country`
- `sector`
- `organization_type`
- `technologies`
- `target_topics`
- `excluded_topics`
- `product_description`
- `risks`

Найважливіші history fields:

- `grant_title`
- `grant_source`
- `program_name`
- `result`
- `country`
- `applicant_type`
- `topics`
- `project_summary`
- `reusable_materials`
- `similarity_weight`

Matching має працювати навіть якщо частина grant fields відсутня.

Відсутні або нечіткі fields створюють `manual_checks`, а не обов'язково ламають match.
