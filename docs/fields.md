# Existing Data Fields

## Sources

Table: `sources`

Fields:

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

Enum values for `access_strategy`:

- `api`
- `wp_rest`
- `rss`
- `sitemap_html`
- `html`
- `browser`
- `manual`

Seeded source slugs:

- `eu-funding`
- `prostir`
- `diia-business`
- `gurt`

## Discovered Grant Items

Таблиця: `discovered_grant_items`

Це реалізована Stage 1 таблиця для item-level результатів пошуку. Вона не замінює `raw_grant_snapshots` і `grants`.

Поля:

- `id`
- `source_id`
- `source_slug`
- `source_url`
- `canonical_url`
- `source_record_id`
- `title_hint`
- `summary_hint`
- `published_at_hint`
- `deadline_hint`
- `listing_url`
- `listing_position`
- `first_seen_at`
- `last_seen_at`
- `discovery_status`
- `detail_fetch_status`
- `content_hash`
- `metadata`

Атрибут моделі для DB-колонки `metadata`:

- `discovery_metadata`

Значення статусу `discovery_status`:

- `new`
- `known`
- `skipped`
- `failed`

Значення статусу `detail_fetch_status`:

- `not_fetched`
- `fetched`
- `failed`
- `skipped_known`

Обмеження та індекси:

- unique: `source_id`, `source_record_id`
- unique: `source_id`, `canonical_url`
- index: `source_id`, `discovery_status`
- index: `source_id`, `detail_fetch_status`
- index: `source_id`, `content_hash`
- index: `last_seen_at`

Як використовується:

- `discover` перечитує listing/RSS/API/search endpoint під час кожного ingestion запуску;
- новизна визначається через `source_record_id`, `canonical_url` або item-level `content_hash`;
- у режимі `incremental` відомий item отримує `discovery_status=known` і `detail_fetch_status=skipped_known`;
- у режимі `backfill` відомий item може повторно пройти `fetch_detail` і `normalize`;
- detail payload після завантаження зберігається не тут, а в `raw_grant_snapshots`.

## Raw Grant Snapshots

Table: `raw_grant_snapshots`

Fields:

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

Model attribute for DB column `metadata`:

- `snapshot_metadata`

Constraints/indexes:

- unique: `source_id`, `source_url`, `content_hash`
- index: `source_id`, `source_record_id`

## Grants

Table: `grants`

Fields:

- `id`
- `created_at`
- `updated_at`
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
- `embedding`
- `embedding_text`
- `embedding_model`
- `embedded_at`

Required fields:

- `source_id`
- `source_url`
- `title`
- `status`

JSON/list fields:

- `countries`
- `regions`
- `applicant_types`
- `topics`
- `keywords`
- `documents`
- `source_metadata`
- `extraction_metadata`

Vector field:

- `embedding`: 1536 dimensions

Constraints/indexes:

- unique: `source_id`, `source_url`
- unique: `source_id`, `source_record_id`
- index: `deadline_at`
- index: `status`

## Client Profiles

Table: `client_profiles`

Fields:

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

Required fields:

- `name`
- `slug`
- `source_type`
- `enabled`

JSON/list fields:

- `technologies`
- `target_topics`
- `excluded_topics`
- `profile_metadata`

Vector field:

- `embedding`: 1536 dimensions

Constraints:

- unique: `slug`

## Application History

Table: `application_history`

Fields:

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

Required fields:

- `client_profile_id`
- `client_name`
- `grant_title`
- `result`
- `similarity_weight`

JSON/list fields:

- `topics`
- `history_metadata`

Vector field:

- `embedding`: 1536 dimensions

Indexes:

- `client_profile_id`, `result`
- `program_name`

## Job Runs

Table: `job_runs`

Fields:

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

Enum values for `job_type`:

- `ingestion`
- `import_clients`
- `import_history`
- `feature_extraction`
- `matching`
- `llm_extraction`
- `embedding`
- `report`
- `seed_sources`

Enum values for `status`:

- `pending`
- `running`
- `success`
- `failed`
- `partial`

JSON fields:

- `job_metadata`

Indexes:

- `job_type`, `status`
- `started_at`

## Match Runs

Table: `match_runs`

Fields:

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

Required fields:

- `run_type`
- `status`
- `parameters`
- `started_at`

JSON fields:

- `parameters`

Indexes:

- `status`

## Grant Client Matches

Table: `grant_client_matches`

Fields:

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

Required fields:

- `match_run_id`
- `grant_id`
- `client_profile_id`
- `score`
- `hard_filter_passed`

JSON/list fields:

- `filter_reasons`
- `manual_checks`
- `evidence`
- `match_metadata`

Constraints/indexes:

- unique: `match_run_id`, `grant_id`, `client_profile_id`
- index: `score`

## Reports

Table: `reports`

Fields:

- `id`
- `created_at`
- `updated_at`
- `match_run_id`
- `title`
- `report_type`
- `format`
- `summary`
- `content`
- `generated_at`
- `report_metadata`

Required fields:

- `title`
- `report_type`
- `format`
- `content`
- `generated_at`

JSON fields:

- `report_metadata`

## NormalizedGrantDraft

Python dataclass: `NormalizedGrantDraft`

Fields:

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

## FetchedGrant

Python dataclass: `FetchedGrant`

Fields:

- `normalized`
- `raw_payload`
- `raw_html`
- `raw_text`
- `raw_title`
- `raw_summary`
- `http_status`
- `content_type`
- `snapshot_metadata`

## FetchedDetail

Python dataclass: `FetchedDetail`

Fields:

- `source_url`
- `raw_payload`
- `raw_html`
- `raw_text`
- `http_status`
- `content_type`
- `metadata`

## ConnectorError

Python dataclass: `ConnectorError`

Fields:

- `message`
- `source_url`
- `stage`
- `metadata`

## ConnectorResult

Python dataclass: `ConnectorResult`

Fields:

- `source_slug`
- `grants`
- `errors`

Properties:

- `fetched_count`
