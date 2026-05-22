from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from grant_tool.db.base import Base


class AccessStrategy(StrEnum):
    API = "api"
    WP_REST = "wp_rest"
    RSS = "rss"
    SITEMAP_HTML = "sitemap_html"
    HTML = "html"
    BROWSER = "browser"
    MANUAL = "manual"


class JobType(StrEnum):
    INGESTION = "ingestion"
    IMPORT_CLIENTS = "import_clients"
    IMPORT_HISTORY = "import_history"
    FEATURE_EXTRACTION = "feature_extraction"
    MATCHING = "matching"
    LLM_EXTRACTION = "llm_extraction"
    EMBEDDING = "embedding"
    REPORT = "report"
    SEED_SOURCES = "seed_sources"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    list_url: Mapped[str | None] = mapped_column(Text)
    api_url: Mapped[str | None] = mapped_column(Text)
    feed_url: Mapped[str | None] = mapped_column(Text)
    sitemap_url: Mapped[str | None] = mapped_column(Text)
    access_strategy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=AccessStrategy.HTML.value,
    )
    requires_browser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rate_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    notes: Mapped[str | None] = mapped_column(Text)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    raw_snapshots: Mapped[list[RawGrantSnapshot]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )
    discovered_items: Mapped[list[DiscoveredGrantItem]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )
    grants: Mapped[list[Grant]] = relationship(back_populates="source")
    job_runs: Mapped[list[JobRun]] = relationship(back_populates="source")


class JobRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        Index("ix_job_runs_job_type_status", "job_type", "status"),
        Index("ix_job_runs_started_at", "started_at"),
    )

    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=JobStatus.PENDING.value,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    job_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    source: Mapped[Source | None] = relationship(back_populates="job_runs")


class RawGrantSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "raw_grant_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "source_url",
            "content_hash",
            name="uq_raw_grant_snapshots_source_url_hash",
        ),
        Index("ix_raw_grant_snapshots_source_record_id", "source_id", "source_record_id"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    raw_title: Mapped[str | None] = mapped_column(Text)
    raw_summary: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    raw_html: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    source: Mapped[Source] = relationship(back_populates="raw_snapshots")
    grants: Mapped[list[Grant]] = relationship(back_populates="latest_raw_snapshot")


class DiscoveredGrantItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "discovered_grant_items"
    __table_args__ = (
        UniqueConstraint("source_id", "source_record_id", name="uq_discovered_items_source_record_id"),
        UniqueConstraint("source_id", "canonical_url", name="uq_discovered_items_canonical_url"),
        Index("ix_discovered_items_source_status", "source_id", "discovery_status"),
        Index("ix_discovered_items_detail_status", "source_id", "detail_fetch_status"),
        Index("ix_discovered_items_last_seen_at", "last_seen_at"),
        Index("ix_discovered_items_content_hash", "source_id", "content_hash"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    title_hint: Mapped[str | None] = mapped_column(Text)
    summary_hint: Mapped[str | None] = mapped_column(Text)
    published_at_hint: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_hint: Mapped[str | None] = mapped_column(Text)
    listing_url: Mapped[str | None] = mapped_column(Text)
    listing_position: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    discovery_status: Mapped[str] = mapped_column(String(50), nullable=False, default="new")
    detail_fetch_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_fetched")
    content_hash: Mapped[str | None] = mapped_column(String(64))
    discovery_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    source: Mapped[Source] = relationship(back_populates="discovered_items")


class Grant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "grants"
    __table_args__ = (
        UniqueConstraint("source_id", "source_url", name="uq_grants_source_url"),
        UniqueConstraint("source_id", "source_record_id", name="uq_grants_source_record_id"),
        Index("ix_grants_deadline_at", "deadline_at"),
        Index("ix_grants_status", "status"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    latest_raw_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("raw_grant_snapshots.id", ondelete="SET NULL"),
    )
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    application_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_text: Mapped[str | None] = mapped_column(Text)
    program_name: Mapped[str | None] = mapped_column(Text)
    funder_name: Mapped[str | None] = mapped_column(Text)
    opportunity_type: Mapped[str | None] = mapped_column(String(100))
    support_type: Mapped[str | None] = mapped_column(String(100))
    funding_amount_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    funding_amount_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    funding_amount_text: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(String(10))
    geography_text: Mapped[str | None] = mapped_column(Text)
    countries: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    regions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    eligibility_text: Mapped[str | None] = mapped_column(Text)
    applicant_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    restrictions_text: Mapped[str | None] = mapped_column(Text)
    cofinancing_required: Mapped[bool | None] = mapped_column(Boolean)
    cofinancing_text: Mapped[str | None] = mapped_column(Text)
    consortium_required: Mapped[bool | None] = mapped_column(Boolean)
    consortium_text: Mapped[str | None] = mapped_column(Text)
    implementation_period_text: Mapped[str | None] = mapped_column(Text)
    contact_text: Mapped[str | None] = mapped_column(Text)
    documents: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    extraction_method: Mapped[str | None] = mapped_column(String(50))
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_review_reason: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    embedding_text: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[Source] = relationship(back_populates="grants")
    latest_raw_snapshot: Mapped[RawGrantSnapshot | None] = relationship(back_populates="grants")
    application_history: Mapped[list[ApplicationHistory]] = relationship(back_populates="grant")
    matches: Mapped[list[GrantClientMatch]] = relationship(back_populates="grant")


class ClientProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "client_profiles"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    country: Mapped[str | None] = mapped_column(String(100))
    sector: Mapped[str | None] = mapped_column(String(255))
    organization_type: Mapped[str | None] = mapped_column(String(100))
    technologies: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    product_description: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[str | None] = mapped_column(Text)
    target_topics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    excluded_topics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    previous_submissions_summary: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    source_uri: Mapped[str | None] = mapped_column(Text)
    profile_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    embedding_text: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application_history: Mapped[list[ApplicationHistory]] = relationship(
        back_populates="client_profile",
        cascade="all, delete-orphan",
    )
    matches: Mapped[list[GrantClientMatch]] = relationship(back_populates="client_profile")


class ApplicationHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "application_history"
    __table_args__ = (
        Index("ix_application_history_client_result", "client_profile_id", "result"),
        Index("ix_application_history_program_name", "program_name"),
    )

    client_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("client_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("grants.id", ondelete="SET NULL"),
    )
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    grant_title: Mapped[str] = mapped_column(Text, nullable=False)
    grant_source: Mapped[str | None] = mapped_column(String(255))
    program_name: Mapped[str | None] = mapped_column(Text)
    application_date: Mapped[date | None] = mapped_column(Date)
    result: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    country: Mapped[str | None] = mapped_column(String(100))
    applicant_type: Mapped[str | None] = mapped_column(String(100))
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    project_summary: Mapped[str | None] = mapped_column(Text)
    reusable_materials: Mapped[str | None] = mapped_column(Text)
    similarity_weight: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text)
    history_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    embedding_text: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client_profile: Mapped[ClientProfile] = relationship(back_populates="application_history")
    grant: Mapped[Grant | None] = relationship(back_populates="application_history")


class MatchRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "match_runs"
    __table_args__ = (Index("ix_match_runs_status", "status"),)

    name: Mapped[str | None] = mapped_column(String(255))
    run_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    matches: Mapped[list[GrantClientMatch]] = relationship(
        back_populates="match_run",
        cascade="all, delete-orphan",
    )
    reports: Mapped[list[Report]] = relationship(back_populates="match_run")


class GrantClientMatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "grant_client_matches"
    __table_args__ = (
        UniqueConstraint(
            "match_run_id",
            "grant_id",
            "client_profile_id",
            name="uq_grant_client_matches_run_grant_client",
        ),
        Index("ix_grant_client_matches_score", "score"),
    )

    match_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("match_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("grants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("client_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    hard_filter_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    filter_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    keyword_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    vector_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    history_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    llm_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    explanation: Mapped[str | None] = mapped_column(Text)
    risks_text: Mapped[str | None] = mapped_column(Text)
    manual_checks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    match_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    match_run: Mapped[MatchRun] = relationship(back_populates="matches")
    grant: Mapped[Grant] = relationship(back_populates="matches")
    client_profile: Mapped[ClientProfile] = relationship(back_populates="matches")


class Report(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reports"

    match_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("match_runs.id", ondelete="SET NULL"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False, default="daily")
    format: Mapped[str] = mapped_column(String(50), nullable=False, default="markdown")
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    report_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    match_run: Mapped[MatchRun | None] = relationship(back_populates="reports")
