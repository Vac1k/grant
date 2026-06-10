from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class DiscoveryMode(StrEnum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"


class DiscoveryStatus(StrEnum):
    NEW = "new"
    KNOWN = "known"
    SKIPPED = "skipped"
    FAILED = "failed"


class DetailFetchStatus(StrEnum):
    NOT_FETCHED = "not_fetched"
    FETCHED = "fetched"
    FAILED = "failed"
    SKIPPED_KNOWN = "skipped_known"


@dataclass(slots=True)
class DiscoveredGrantItemDraft:
    source_url: str
    canonical_url: str | None = None
    source_record_id: str | None = None
    title_hint: str | None = None
    summary_hint: str | None = None
    published_at_hint: datetime | None = None
    deadline_hint: str | None = None
    listing_url: str | None = None
    listing_position: int | None = None
    content_hash: str | None = None
    discovery_metadata: dict[str, Any] = field(default_factory=dict)

    def identity_metadata(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "canonical_url": self.canonical_url,
            "source_record_id": self.source_record_id,
            "title_hint": self.title_hint,
            "listing_url": self.listing_url,
            "listing_position": self.listing_position,
            "content_hash": self.content_hash,
        }


@dataclass(slots=True)
class NormalizedGrantDraft:
    source_url: str
    title: str
    status: str = "unknown"
    source_record_id: str | None = None
    application_url: str | None = None
    summary: str | None = None
    description_text: str | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    deadline_text: str | None = None
    program_name: str | None = None
    funder_name: str | None = None
    opportunity_type: str | None = None
    support_type: str | None = None
    funding_amount_min: Decimal | None = None
    funding_amount_max: Decimal | None = None
    funding_amount_text: str | None = None
    currency: str | None = None
    geography_text: str | None = None
    countries: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    eligibility_text: str | None = None
    applicant_types: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    restrictions_text: str | None = None
    cofinancing_text: str | None = None
    consortium_text: str | None = None
    documents: list[dict[str, Any]] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    extraction_confidence: Decimal | None = None
    extraction_metadata: dict[str, Any] = field(default_factory=dict)
    needs_manual_review: bool = False
    manual_review_reason: str | None = None

    def to_grant_fields(self) -> dict[str, Any]:
        return {
            "application_url": self.application_url,
            "summary": self.summary,
            "description_text": self.description_text,
            "published_at": self.published_at,
            "deadline_at": self.deadline_at,
            "deadline_text": self.deadline_text,
            "program_name": self.program_name,
            "funder_name": self.funder_name,
            "opportunity_type": self.opportunity_type,
            "support_type": self.support_type,
            "funding_amount_min": self.funding_amount_min,
            "funding_amount_max": self.funding_amount_max,
            "funding_amount_text": self.funding_amount_text,
            "currency": self.currency,
            "geography_text": self.geography_text,
            "countries": self.countries,
            "regions": self.regions,
            "eligibility_text": self.eligibility_text,
            "applicant_types": self.applicant_types,
            "topics": self.topics,
            "keywords": self.keywords,
            "restrictions_text": self.restrictions_text,
            "cofinancing_text": self.cofinancing_text,
            "consortium_text": self.consortium_text,
            "documents": self.documents,
            "source_metadata": self.source_metadata,
            "extraction_confidence": self.extraction_confidence,
            "extraction_metadata": self.extraction_metadata,
            "needs_manual_review": self.needs_manual_review,
            "manual_review_reason": self.manual_review_reason,
        }


@dataclass(slots=True)
class FetchedDetail:
    source_url: str
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_html: str | None = None
    raw_text: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FetchedGrant:
    normalized: NormalizedGrantDraft
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_html: str | None = None
    raw_text: str | None = None
    raw_title: str | None = None
    raw_summary: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    snapshot_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConnectorError:
    message: str
    source_url: str | None = None
    stage: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConnectorResult:
    source_slug: str
    grants: list[FetchedGrant] = field(default_factory=list)
    errors: list[ConnectorError] = field(default_factory=list)

    @property
    def fetched_count(self) -> int:
        return len(self.grants)
