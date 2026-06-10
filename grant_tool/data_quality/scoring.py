from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from grant_tool.data_quality.contract import (
    GrantClassification,
    GrantQualityEvaluation,
    GrantQualityTier,
    QualityFlag,
    SourceFamily,
    evaluate_grant_quality_contract,
)
from grant_tool.ingestion.utils import clean_text


QUALITY_SCORING_VERSION = "data-preparation-step7-v1"
DEFAULT_MIN_MATCHING_QUALITY_SCORE = 40

# Positive components sum to exactly 100 for a fully populated record.
CORE_COMPONENT_POINTS = {
    "core_title": 10,
    "core_source_url": 10,
    "core_context_text": 10,
    "core_valid_status": 10,
}
IMPORTANT_FIELD_POINTS = {
    QualityFlag.MISSING_DEADLINE: ("important_deadline", 8),
    QualityFlag.MISSING_FUNDER: ("important_funder", 4),
    QualityFlag.MISSING_AMOUNT: ("important_amount", 4),
    QualityFlag.MISSING_CURRENCY: ("important_currency", 2),
    QualityFlag.MISSING_COUNTRY: ("important_country", 4),
    QualityFlag.MISSING_REGION: ("important_region", 1),
    QualityFlag.MISSING_ELIGIBILITY: ("important_eligibility", 4),
    QualityFlag.MISSING_APPLICATION_URL: ("important_application_url", 2),
    QualityFlag.MISSING_PUBLISHED_AT: ("important_published_at", 1),
}
ADVANCED_SIGNAL_FIELDS = ("program_name", "keywords", "restrictions_text", "funding_amount_max", "documents")
ADVANCED_SIGNAL_MAX_POINTS = 5
TEXT_SUMMARY_POINTS = 5
TEXT_DESCRIPTION_POINTS = 5
STATUS_POINTS = {"open": 5, "unknown": 2, "closed": 0}
SOURCE_FAMILY_POINTS = {
    SourceFamily.STRUCTURED_DIRECT: 10,
    SourceFamily.USEFUL_INCOMPLETE: 7,
    SourceFamily.UNKNOWN: 5,
    SourceFamily.AGGREGATOR: 4,
    SourceFamily.DIGEST_HEAVY: 2,
    SourceFamily.EMPTY_OR_PROBLEM: 0,
}
PENALTY_POINTS = {
    QualityFlag.NOISE_REJECTED: ("penalty_noise_classification", 60),
    QualityFlag.NEEDS_MANUAL_REVIEW: ("penalty_manual_review", 15),
    QualityFlag.SOURCE_CLASSIFICATION_UNCERTAIN: ("penalty_classification_uncertain", 10),
    QualityFlag.LOW_EXTRACTION_CONFIDENCE: ("penalty_low_extraction_confidence", 10),
    QualityFlag.POSSIBLE_DUPLICATE: ("penalty_possible_duplicate", 10),
    QualityFlag.BROAD_FINANCE_PROGRAM: ("penalty_broad_finance_program", 5),
}


@dataclass(frozen=True, slots=True)
class GrantQualityScore:
    score: int
    tier: GrantQualityTier
    classification: GrantClassification
    flags: tuple[QualityFlag, ...]
    components: dict[str, int]
    penalties: dict[str, int]
    matching_ready: bool
    evaluation: GrantQualityEvaluation


def compute_grant_quality_score(
    grant: Any,
    *,
    min_matching_quality_score: int = DEFAULT_MIN_MATCHING_QUALITY_SCORE,
) -> GrantQualityScore:
    evaluation = evaluate_grant_quality_contract(grant)
    flags = set(evaluation.flags)
    components: dict[str, int] = {}
    penalties: dict[str, int] = {}

    core_checks = {
        "core_title": QualityFlag.WEAK_TITLE not in flags,
        "core_source_url": QualityFlag.MISSING_SOURCE_URL not in flags,
        "core_context_text": QualityFlag.MISSING_CONTEXT_TEXT not in flags,
        "core_valid_status": QualityFlag.INVALID_STATUS not in flags,
    }
    for name, passed in core_checks.items():
        if passed:
            components[name] = CORE_COMPONENT_POINTS[name]

    for flag, (name, points) in IMPORTANT_FIELD_POINTS.items():
        if flag not in flags:
            components[name] = points

    advanced_points = sum(
        1 for field_name in ADVANCED_SIGNAL_FIELDS if _field_present(grant, field_name)
    )
    if advanced_points:
        components["advanced_fields"] = min(advanced_points, ADVANCED_SIGNAL_MAX_POINTS)

    summary = clean_text(getattr(grant, "summary", None)) or ""
    description = clean_text(getattr(grant, "description_text", None)) or ""
    if len(summary) >= 80:
        components["text_summary"] = TEXT_SUMMARY_POINTS
    if len(description) >= 300:
        components["text_description"] = TEXT_DESCRIPTION_POINTS

    status = clean_text(getattr(grant, "status", None)) or "unknown"
    status_points = STATUS_POINTS.get(status, 0)
    if status_points:
        components["status"] = status_points

    family_points = SOURCE_FAMILY_POINTS.get(evaluation.source_family, 0)
    if family_points:
        components["source_family"] = family_points

    for flag, (name, points) in PENALTY_POINTS.items():
        if flag in flags:
            penalties[name] = points

    raw_score = sum(components.values()) - sum(penalties.values())
    score = max(0, min(100, raw_score))
    matching_ready = evaluation.matching_eligible and score >= min_matching_quality_score

    return GrantQualityScore(
        score=score,
        tier=evaluation.tier,
        classification=evaluation.classification,
        flags=evaluation.flags,
        components=components,
        penalties=penalties,
        matching_ready=matching_ready,
        evaluation=evaluation,
    )


def apply_grant_quality_score(
    grant: Any,
    *,
    min_matching_quality_score: int = DEFAULT_MIN_MATCHING_QUALITY_SCORE,
) -> GrantQualityScore:
    """Compute and persist quality fields on the grant record.

    Persists the compact score/tier/flags columns and keeps the explainable
    breakdown in extraction_metadata["quality"] for auditability.
    """
    result = compute_grant_quality_score(grant, min_matching_quality_score=min_matching_quality_score)
    grant.quality_score = result.score
    grant.quality_tier = result.tier.value
    grant.quality_flags = [flag.value for flag in result.flags]
    metadata = dict(getattr(grant, "extraction_metadata", None) or {})
    metadata["quality"] = {
        "version": QUALITY_SCORING_VERSION,
        "score": result.score,
        "tier": result.tier.value,
        "classification": result.classification.value,
        "flags": [flag.value for flag in result.flags],
        "components": dict(result.components),
        "penalties": dict(result.penalties),
        "matching_ready": result.matching_ready,
        "min_matching_quality_score": min_matching_quality_score,
    }
    grant.extraction_metadata = metadata
    return result


def _field_present(grant: Any, field_name: str) -> bool:
    value = getattr(grant, field_name, None)
    if isinstance(value, str):
        return bool(clean_text(value))
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return value is not None
