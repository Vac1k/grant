from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from grant_tool.ingestion.utils import clean_text


class GrantStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class GrantQualityTier(StrEnum):
    MATCH_READY = "match_ready"
    USABLE_WITH_WARNINGS = "usable_with_warnings"
    NEEDS_REVIEW = "needs_review"
    NOISE_REJECTED = "noise_rejected"


class GrantClassification(StrEnum):
    GRANT = "grant"
    BUSINESS_SUPPORT = "business_support"
    FINANCE_PROGRAM = "finance_program"
    OPPORTUNITY = "opportunity"
    DIGEST = "digest"
    NEWS = "news"
    ARTICLE = "article"
    EVENT = "event"
    WEBINAR = "webinar"
    TRAINING = "training"
    TENDER = "tender"
    UNKNOWN = "unknown"


class QualityFlag(StrEnum):
    WEAK_TITLE = "weak_title"
    MISSING_SOURCE_URL = "missing_source_url"
    MISSING_CONTEXT_TEXT = "missing_context_text"
    INVALID_STATUS = "invalid_status"
    STATUS_UNKNOWN = "status_unknown"
    CLOSED_STATUS = "closed_status"
    MISSING_DEADLINE = "missing_deadline"
    MISSING_AMOUNT = "missing_amount"
    MISSING_CURRENCY = "missing_currency"
    MISSING_FUNDER = "missing_funder"
    MISSING_COUNTRY = "missing_country"
    MISSING_REGION = "missing_region"
    MISSING_ELIGIBILITY = "missing_eligibility"
    MISSING_APPLICATION_URL = "missing_application_url"
    MISSING_PUBLISHED_AT = "missing_published_at"
    BROAD_FINANCE_PROGRAM = "broad_finance_program"
    POSSIBLE_DIGEST = "possible_digest"
    POSSIBLE_NEWS = "possible_news"
    POSSIBLE_EVENT = "possible_event"
    POSSIBLE_WEBINAR = "possible_webinar"
    POSSIBLE_TRAINING = "possible_training"
    POSSIBLE_TENDER = "possible_tender"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    LOW_EXTRACTION_CONFIDENCE = "low_extraction_confidence"
    NOISE_REJECTED = "noise_rejected"


class ManualReviewRule(StrEnum):
    EXPLICIT_MANUAL_REVIEW = "explicit_manual_review"
    CORE_CONTEXT_MISSING = "core_context_missing"
    INVALID_STATUS = "invalid_status"
    LOW_EXTRACTION_CONFIDENCE = "low_extraction_confidence"
    NOISE_OR_NON_GRANT = "noise_or_non_grant"


class SourceFamily(StrEnum):
    STRUCTURED_DIRECT = "structured_direct"
    USEFUL_INCOMPLETE = "useful_incomplete"
    DIGEST_HEAVY = "digest_heavy"
    AGGREGATOR = "aggregator"
    EMPTY_OR_PROBLEM = "empty_or_problem"
    UNKNOWN = "unknown"


CORE_FIELDS = (
    "title",
    "source_url",
    "source_id",
    "source_slug",
    "summary_or_sufficient_text",
    "status",
    "needs_manual_review",
    "manual_review_reason",
)
IMPORTANT_OPTIONAL_FIELDS = (
    "deadline_at",
    "deadline_text",
    "funder_name",
    "funding_amount_text",
    "currency",
    "country",
    "region",
    "support_type",
    "eligibility_text",
    "application_url",
    "source_published_at",
)
ADVANCED_ENRICHMENT_FIELDS = (
    "funding_amount_min",
    "funding_amount_max",
    "opportunity_type",
    "program_name",
    "keywords",
    "restrictions_text",
    "cofinancing_required",
    "cofinancing_text",
    "consortium_required",
    "consortium_text",
    "implementation_period_text",
    "contact_text",
    "documents",
    "extraction_confidence",
    "extraction_metadata",
    "embedding",
    "embedding_text",
    "embedding_model",
    "embedded_at",
)

ALLOWED_STATUSES = frozenset(status.value for status in GrantStatus)
ALLOWED_CLASSIFICATIONS = frozenset(classification.value for classification in GrantClassification)
NOISE_CLASSIFICATIONS = frozenset(
    {
        GrantClassification.DIGEST,
        GrantClassification.NEWS,
        GrantClassification.ARTICLE,
        GrantClassification.EVENT,
        GrantClassification.WEBINAR,
        GrantClassification.TRAINING,
        GrantClassification.TENDER,
    }
)
MATCHING_ALLOWED_TIERS = frozenset(
    {
        GrantQualityTier.MATCH_READY,
        GrantQualityTier.USABLE_WITH_WARNINGS,
    }
)

SOURCE_FAMILY_BY_SLUG: dict[str, SourceFamily] = {
    "diia-business": SourceFamily.STRUCTURED_DIRECT,
    "eu-funding": SourceFamily.STRUCTURED_DIRECT,
    "grantforward": SourceFamily.STRUCTURED_DIRECT,
    "chas-zmin": SourceFamily.USEFUL_INCOMPLETE,
    "grant-market": SourceFamily.USEFUL_INCOMPLETE,
    "prostir": SourceFamily.USEFUL_INCOMPLETE,
    "nipo": SourceFamily.DIGEST_HEAVY,
    "hromady": SourceFamily.DIGEST_HEAVY,
    "fundsforngos": SourceFamily.DIGEST_HEAVY,
    "opportunitydesk": SourceFamily.DIGEST_HEAVY,
    "eufundingportal-eu": SourceFamily.AGGREGATOR,
    "gurt": SourceFamily.EMPTY_OR_PROBLEM,
}


@dataclass(frozen=True, slots=True)
class GrantQualityContract:
    allowed_statuses: frozenset[str]
    allowed_classifications: frozenset[str]
    noise_classifications: frozenset[GrantClassification]
    matching_allowed_tiers: frozenset[GrantQualityTier]
    core_fields: tuple[str, ...]
    important_optional_fields: tuple[str, ...]
    advanced_enrichment_fields: tuple[str, ...]
    source_family_by_slug: dict[str, SourceFamily]


@dataclass(frozen=True, slots=True)
class GrantQualityEvaluation:
    tier: GrantQualityTier
    classification: GrantClassification
    flags: tuple[QualityFlag, ...]
    manual_review_rules: tuple[ManualReviewRule, ...]
    matching_eligible: bool
    matching_blockers: tuple[str, ...]
    source_family: SourceFamily
    core_complete: bool
    important_missing_fields: tuple[str, ...]


DEFAULT_GRANT_QUALITY_CONTRACT = GrantQualityContract(
    allowed_statuses=ALLOWED_STATUSES,
    allowed_classifications=ALLOWED_CLASSIFICATIONS,
    noise_classifications=NOISE_CLASSIFICATIONS,
    matching_allowed_tiers=MATCHING_ALLOWED_TIERS,
    core_fields=CORE_FIELDS,
    important_optional_fields=IMPORTANT_OPTIONAL_FIELDS,
    advanced_enrichment_fields=ADVANCED_ENRICHMENT_FIELDS,
    source_family_by_slug=SOURCE_FAMILY_BY_SLUG,
)


def evaluate_grant_quality_contract(
    grant: Any,
    *,
    contract: GrantQualityContract = DEFAULT_GRANT_QUALITY_CONTRACT,
) -> GrantQualityEvaluation:
    flags: list[QualityFlag] = []
    manual_review_rules: list[ManualReviewRule] = []
    matching_blockers: list[str] = []
    important_missing_fields: list[str] = []

    title = clean_text(getattr(grant, "title", None)) or ""
    source_url = clean_text(getattr(grant, "source_url", None)) or ""
    status = clean_text(getattr(grant, "status", None)) or GrantStatus.UNKNOWN.value
    classification = _classification_for_grant(grant)
    source_family = contract.source_family_by_slug.get(_source_slug(grant) or "", SourceFamily.UNKNOWN)

    if len(title) < 8:
        _append_once(flags, QualityFlag.WEAK_TITLE)
        matching_blockers.append(QualityFlag.WEAK_TITLE.value)
    if not source_url.startswith("http"):
        _append_once(flags, QualityFlag.MISSING_SOURCE_URL)
        matching_blockers.append(QualityFlag.MISSING_SOURCE_URL.value)

    if status not in contract.allowed_statuses:
        _append_once(flags, QualityFlag.INVALID_STATUS)
        _append_once(manual_review_rules, ManualReviewRule.INVALID_STATUS)
        matching_blockers.append(QualityFlag.INVALID_STATUS.value)
    elif status == GrantStatus.UNKNOWN.value:
        _append_once(flags, QualityFlag.STATUS_UNKNOWN)
    elif status == GrantStatus.CLOSED.value:
        _append_once(flags, QualityFlag.CLOSED_STATUS)
        matching_blockers.append(QualityFlag.CLOSED_STATUS.value)

    if not _has_sufficient_context(grant, title=title):
        _append_once(flags, QualityFlag.MISSING_CONTEXT_TEXT)
        _append_once(manual_review_rules, ManualReviewRule.CORE_CONTEXT_MISSING)
        matching_blockers.append(QualityFlag.MISSING_CONTEXT_TEXT.value)

    _add_optional_field_flags(grant, flags, important_missing_fields)
    _add_contract_risk_flags(grant, classification, flags)

    if getattr(grant, "needs_manual_review", False):
        _append_once(flags, QualityFlag.NEEDS_MANUAL_REVIEW)
        _append_once(manual_review_rules, ManualReviewRule.EXPLICIT_MANUAL_REVIEW)
        matching_blockers.append(QualityFlag.NEEDS_MANUAL_REVIEW.value)

    extraction_confidence = getattr(grant, "extraction_confidence", None)
    if extraction_confidence is not None and Decimal(str(extraction_confidence)) < Decimal("0.5000"):
        _append_once(flags, QualityFlag.LOW_EXTRACTION_CONFIDENCE)
        _append_once(manual_review_rules, ManualReviewRule.LOW_EXTRACTION_CONFIDENCE)
        matching_blockers.append(QualityFlag.LOW_EXTRACTION_CONFIDENCE.value)

    if classification in contract.noise_classifications:
        _append_once(flags, QualityFlag.NOISE_REJECTED)
        _append_once(manual_review_rules, ManualReviewRule.NOISE_OR_NON_GRANT)
        matching_blockers.append(QualityFlag.NOISE_REJECTED.value)

    core_complete = not any(
        blocker
        in {
            QualityFlag.WEAK_TITLE.value,
            QualityFlag.MISSING_SOURCE_URL.value,
            QualityFlag.MISSING_CONTEXT_TEXT.value,
            QualityFlag.INVALID_STATUS.value,
        }
        for blocker in matching_blockers
    )

    if classification in contract.noise_classifications:
        tier = GrantQualityTier.NOISE_REJECTED
    elif (
        QualityFlag.NEEDS_MANUAL_REVIEW in flags
        or QualityFlag.INVALID_STATUS in flags
        or QualityFlag.MISSING_CONTEXT_TEXT in flags
        or QualityFlag.WEAK_TITLE in flags
        or QualityFlag.MISSING_SOURCE_URL in flags
        or QualityFlag.LOW_EXTRACTION_CONFIDENCE in flags
    ):
        tier = GrantQualityTier.NEEDS_REVIEW
    elif _has_only_soft_warnings(flags):
        tier = GrantQualityTier.USABLE_WITH_WARNINGS
    else:
        tier = GrantQualityTier.MATCH_READY

    matching_eligible = tier in contract.matching_allowed_tiers and not matching_blockers

    return GrantQualityEvaluation(
        tier=tier,
        classification=classification,
        flags=tuple(flags),
        manual_review_rules=tuple(manual_review_rules),
        matching_eligible=matching_eligible,
        matching_blockers=tuple(dict.fromkeys(matching_blockers)),
        source_family=source_family,
        core_complete=core_complete,
        important_missing_fields=tuple(dict.fromkeys(important_missing_fields)),
    )


def _classification_for_grant(grant: Any) -> GrantClassification:
    values = [
        _metadata_value(getattr(grant, "extraction_metadata", None), "classification"),
        _metadata_value(getattr(grant, "source_metadata", None), "classification"),
        getattr(grant, "opportunity_type", None),
        getattr(grant, "support_type", None),
    ]
    for value in values:
        classification = _classification_from_value(value)
        if classification is not None:
            return classification
    return GrantClassification.UNKNOWN


def _classification_from_value(value: Any) -> GrantClassification | None:
    text = (clean_text(str(value)) or "").lower().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    aliases = {
        "grant": GrantClassification.GRANT,
        "grants": GrantClassification.GRANT,
        "business_support": GrantClassification.BUSINESS_SUPPORT,
        "finance_program": GrantClassification.FINANCE_PROGRAM,
        "finance_programme": GrantClassification.FINANCE_PROGRAM,
        "program": GrantClassification.FINANCE_PROGRAM,
        "programme": GrantClassification.FINANCE_PROGRAM,
        "opportunity": GrantClassification.OPPORTUNITY,
        "digest": GrantClassification.DIGEST,
        "news": GrantClassification.NEWS,
        "article": GrantClassification.ARTICLE,
        "event": GrantClassification.EVENT,
        "webinar": GrantClassification.WEBINAR,
        "training": GrantClassification.TRAINING,
        "course": GrantClassification.TRAINING,
        "tender": GrantClassification.TENDER,
        "procurement": GrantClassification.TENDER,
        "unknown": GrantClassification.UNKNOWN,
    }
    return aliases.get(text)


def _source_slug(grant: Any) -> str | None:
    source = getattr(grant, "source", None)
    return clean_text(getattr(source, "slug", None))


def _metadata_value(metadata: Any, key: str) -> Any:
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


def _has_sufficient_context(grant: Any, *, title: str) -> bool:
    text_fields = (
        getattr(grant, "summary", None),
        getattr(grant, "description_text", None),
        getattr(grant, "eligibility_text", None),
        getattr(grant, "restrictions_text", None),
    )
    if any(clean_text(value) for value in text_fields):
        return True
    taxonomy_or_terms = any(
        bool(getattr(grant, field_name, None) or [])
        for field_name in ("topics", "keywords", "applicant_types", "countries", "regions")
    )
    structured_context = any(
        clean_text(getattr(grant, field_name, None))
        for field_name in ("deadline_text", "funding_amount_text", "funder_name", "program_name")
    )
    return len(title) >= 20 and (taxonomy_or_terms or structured_context)


def _add_optional_field_flags(
    grant: Any,
    flags: list[QualityFlag],
    important_missing_fields: list[str],
) -> None:
    missing_checks = (
        ("deadline", QualityFlag.MISSING_DEADLINE, not (getattr(grant, "deadline_at", None) or clean_text(getattr(grant, "deadline_text", None)))),
        ("funding_amount_text", QualityFlag.MISSING_AMOUNT, not clean_text(getattr(grant, "funding_amount_text", None))),
        ("currency", QualityFlag.MISSING_CURRENCY, not clean_text(getattr(grant, "currency", None))),
        ("funder_name", QualityFlag.MISSING_FUNDER, not clean_text(getattr(grant, "funder_name", None))),
        ("country", QualityFlag.MISSING_COUNTRY, not bool(getattr(grant, "countries", None) or [])),
        ("region", QualityFlag.MISSING_REGION, not bool(getattr(grant, "regions", None) or [])),
        ("eligibility_text", QualityFlag.MISSING_ELIGIBILITY, not clean_text(getattr(grant, "eligibility_text", None))),
        ("application_url", QualityFlag.MISSING_APPLICATION_URL, not clean_text(getattr(grant, "application_url", None))),
        ("source_published_at", QualityFlag.MISSING_PUBLISHED_AT, getattr(grant, "published_at", None) is None),
    )
    for field_name, flag, missing in missing_checks:
        if missing:
            _append_once(flags, flag)
            important_missing_fields.append(field_name)


def _add_contract_risk_flags(
    grant: Any,
    classification: GrantClassification,
    flags: list[QualityFlag],
) -> None:
    if classification == GrantClassification.FINANCE_PROGRAM:
        _append_once(flags, QualityFlag.BROAD_FINANCE_PROGRAM)
    if classification == GrantClassification.DIGEST:
        _append_once(flags, QualityFlag.POSSIBLE_DIGEST)
    if classification == GrantClassification.NEWS:
        _append_once(flags, QualityFlag.POSSIBLE_NEWS)
    if classification == GrantClassification.EVENT:
        _append_once(flags, QualityFlag.POSSIBLE_EVENT)
    if classification == GrantClassification.WEBINAR:
        _append_once(flags, QualityFlag.POSSIBLE_WEBINAR)
    if classification == GrantClassification.TRAINING:
        _append_once(flags, QualityFlag.POSSIBLE_TRAINING)
    if classification == GrantClassification.TENDER:
        _append_once(flags, QualityFlag.POSSIBLE_TENDER)

    metadata = getattr(grant, "source_metadata", None)
    if isinstance(metadata, dict):
        quality_reasons = metadata.get("quality_reasons") or []
        if any(str(reason) == "duplicate_risk_with_official_eu_source" for reason in quality_reasons):
            _append_once(flags, QualityFlag.POSSIBLE_DUPLICATE)


def _has_only_soft_warnings(flags: list[QualityFlag]) -> bool:
    hard_flags = {
        QualityFlag.WEAK_TITLE,
        QualityFlag.MISSING_SOURCE_URL,
        QualityFlag.MISSING_CONTEXT_TEXT,
        QualityFlag.INVALID_STATUS,
        QualityFlag.NEEDS_MANUAL_REVIEW,
        QualityFlag.NOISE_REJECTED,
    }
    return any(flag not in hard_flags for flag in flags)


def _append_once(items: list[Any], item: Any) -> None:
    if item not in items:
        items.append(item)
