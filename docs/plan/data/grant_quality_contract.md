# Grant Quality Contract

Дата: `2026-06-02`.

Цей документ визначає app-facing contract для normalized records у таблиці `grants`.

Contract не змінює schema і не видаляє дані. Він визначає, як app має оцінювати records для dashboard, matching, manual review і майбутнього quality score.

Code-level реалізація contract знаходиться в:

- `grant_tool/data_quality/contract.py`;
- `tests/test_data_quality_contract.py`.

## Дозволені Status Values

Allowed statuses:

- `open`;
- `closed`;
- `unknown`.

Інші значення вважаються `invalid_status` і переводять record у `needs_review`.

`unknown` не є автоматичним reject. Це warning, бо багато джерел не дають стабільний статус.

`closed` не є noise, але не допускається в active matching, якщо користувач явно не просить historical opportunities.

## Quality Tiers

### `match_ready`

Record можна використовувати в active matching і показувати як нормальну opportunity.

Умови:

- є core identity/context;
- status дозволений і не `closed`;
- немає explicit `needs_manual_review`;
- classification не є noise/non-grant;
- немає blocking quality flags.

### `usable_with_warnings`

Record можна показувати або використовувати обережно, але app має мати warnings.

Типові причини:

- `status_unknown`;
- missing `deadline`;
- missing `funder_name`;
- missing `region`;
- missing `application_url`;
- missing `published_at`;
- broader `finance_program`.

Ці missing fields не є global reject, бо Step 1 показав, що вони масово відсутні в реальному dataset.

### `needs_review`

Record зберігається, але не має автоматично потрапляти в active matching.

Типові причини:

- explicit `needs_manual_review`;
- weak/missing title;
- invalid/missing source URL;
- недостатній context text;
- invalid status;
- low extraction confidence.

### `noise_rejected`

Record схожий на non-grant або шум і не має потрапляти в matching.

Типові classification values:

- `digest`;
- `news`;
- `article`;
- `event`;
- `webinar`;
- `training`;
- `tender`.

## Classification Values

Allowed classifications:

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

Evaluator використовує explicit fields:

- `opportunity_type`;
- `support_type`;
- `source_metadata.classification`;
- `extraction_metadata.classification`.

Після Step 3 evaluator також використовує deterministic title/content markers для obvious noise і direct grant signals.

## Matching Gate

Active matching бере тільки records, які:

- мають tier `match_ready` або `usable_with_warnings`;
- не classified як noise/non-grant;
- не мають explicit `needs_manual_review`;
- не мають `closed` status;
- мають core identity/context;
- мають достатній text або structured context для matching.

Records з tier `needs_review` або `noise_rejected` не мають автоматично потрапляти в active matching.

## Core Fields

Core fields:

- `title`;
- `source_url`;
- `source_id`;
- `source_slug`;
- `summary_or_sufficient_text`;
- `status`;
- `needs_manual_review`;
- `manual_review_reason`.

Core fields визначають, чи record можна оцінити. Вони не гарантують `match_ready`.

## Important Optional Fields

Important optional fields:

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

Ці fields впливають на warning flags, ranking, dashboard trust і explainability.

Вони не є global hard requirements для всіх sources.

## Advanced / Enrichment Fields

Advanced fields:

- `funding_amount_min`;
- `funding_amount_max`;
- `opportunity_type`;
- `program_name`;
- `keywords`;
- `restrictions_text`;
- `cofinancing_text`;
- `consortium_text`;
- `documents`;
- `extraction_confidence`;
- `extraction_metadata`;
- `embedding`;
- `embedding_text`;
- `embedding_model`;
- `embedded_at`.

Ці fields покращують matching/scoring, але не required для ingestion.

## Quality Flags

Code-level flags:

- `weak_title`;
- `missing_source_url`;
- `missing_context_text`;
- `invalid_status`;
- `status_unknown`;
- `closed_status`;
- `missing_deadline`;
- `missing_amount`;
- `missing_currency`;
- `missing_funder`;
- `missing_country`;
- `missing_region`;
- `missing_eligibility`;
- `missing_application_url`;
- `missing_published_at`;
- `broad_finance_program`;
- `possible_digest`;
- `possible_news`;
- `possible_event`;
- `possible_webinar`;
- `possible_training`;
- `possible_tender`;
- `possible_duplicate`;
- `source_classification_uncertain`;
- `needs_manual_review`;
- `low_extraction_confidence`;
- `noise_rejected`.

## Manual Review Rules

Manual review rules:

- `explicit_manual_review`;
- `core_context_missing`;
- `invalid_status`;
- `low_extraction_confidence`;
- `noise_or_non_grant`;
- `source_classification_uncertain`.

## Source Families

Source-level contract:

- `structured_direct`:
  - `diia-business`;
  - `eu-funding`;
  - `grantforward`.
- `useful_incomplete`:
  - `chas-zmin`;
  - `grant-market`;
  - `prostir`.
- `digest_heavy`:
  - `nipo`;
  - `hromady`;
  - `fundsforngos`;
  - `opportunitydesk`.
- `aggregator`:
  - `eufundingportal-eu`.
- `empty_or_problem`:
  - `gurt`.

## Implementation Boundary

Step 2 defined and tested the contract.

Step 3 implemented deterministic classification and wired the matching gate into shortlist matching.

Step 4 implemented deterministic critical-field normalization in Stage 5 extraction, including status, deadline, amount text, currency, geography, funder fallback, support type and eligibility cleanup.

Step 5 implemented soft deduplication metadata and matching gate behavior for non-primary duplicate records. `possible_duplicate` can now come from `extraction_metadata.deduplication`.

Step 6 implemented validated optional AI fallback for weak extraction fields. AI output is stored under `extraction_metadata.llm`; validated AI classification may populate `extraction_metadata.classification` only when no existing classification is present.

Step 7 implemented persisted deterministic quality scoring on top of this contract:

- `grants.quality_score`: deterministic `0-100` score;
- `grants.quality_tier`: persisted contract tier;
- `grants.quality_flags`: persisted contract flag values;
- `extraction_metadata.quality`: explainable component/penalty breakdown with scoring version;
- score components: core fields (40), important optional fields (30), advanced fields as weak signal (max 5), summary/description richness (10), status (5), source family (10);
- penalties: noise classification (60), manual review (15), uncertain source classification (10), low extraction confidence (10), possible duplicate (10), broad finance program (5);
- scoring runs inside `extract-features`, after `deduplicate`, and on demand via `grant-tool quality-score`;
- matching hard-filters records with persisted score below the threshold (`quality_gate:low_quality_score:<score>`, default threshold 40) unless `--include-low-quality` is passed.

Step 8 implemented the prepared grants layer as persisted quality fields on `grants` plus `GrantRepository.list_prepared_grants` and dashboard quality state. No separate `prepared_grants` table or view was created; the decision is documented in `implemented_for_data.md`.

The contract still does not delete noise records; they stay soft-rejected via tier, flags, and the matching gate.
