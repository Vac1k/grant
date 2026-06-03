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

The contract still does not:

- persist `quality_score`;
- persist `quality_flags`;
- add DB columns;
- delete noise records;

Persisted scoring/flags and prepared data structures belong to Step 7 and Step 8.
