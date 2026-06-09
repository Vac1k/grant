from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from grant_tool.db.models import (
    AccessStrategy,
    ApplicationHistory,
    ClientProfile,
    DiscoveredGrantItem,
    Grant,
    GrantClientMatch,
    JobRun,
    JobStatus,
    JobType,
    MatchRun,
    RawGrantSnapshot,
    Report,
    Source,
)
from grant_tool.ingestion.types import DetailFetchStatus, DiscoveredGrantItemDraft, DiscoveryStatus


def _enum_value(value: str | StrEnum) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return value


def _merge_metadata(
    current: dict[str, Any] | None,
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    return {**(current or {}), **(extra or {})}


@dataclass(slots=True)
class SearchSourceReportRow:
    source_slug: str
    enabled: bool
    discovered_total: int
    discovery_new: int
    discovery_known: int
    discovery_failed: int
    detail_not_fetched: int
    detail_fetched: int
    detail_failed: int
    detail_skipped_known: int
    grants_total: int
    grants_open: int
    grants_unknown: int
    grants_manual_review: int
    last_seen_at: datetime | None
    latest_job_status: str | None
    latest_job_processed: int
    latest_job_created: int
    latest_job_updated: int
    latest_job_skipped: int
    latest_job_failed: int
    latest_job_refresh_due: int
    latest_job_refreshed_known: int


@dataclass(slots=True)
class SearchQualityGrantSample:
    title: str
    status: str
    deadline_text: str | None
    funding_amount_text: str | None
    source_url: str
    needs_manual_review: bool


@dataclass(slots=True)
class SearchQualityGateRow:
    source_slug: str
    required: bool
    required_count: int
    grants_total: int
    quality_approved_count: int
    rejected_count: int
    passed: bool
    samples: list[SearchQualityGrantSample]


@dataclass(slots=True)
class DataAuditFieldCompleteness:
    field_name: str
    populated_count: int
    missing_count: int
    total_count: int


@dataclass(slots=True)
class DataAuditGrantSample:
    title: str
    status: str
    source_url: str
    reasons: list[str]
    manual_review_reason: str | None = None


@dataclass(slots=True)
class DataAuditSourceRow:
    source_slug: str
    grants_total: int
    status_counts: dict[str, int]
    manual_review_count: int
    field_completeness: list[DataAuditFieldCompleteness]
    weak_record_count: int
    noise_candidate_count: int
    weak_samples: list[DataAuditGrantSample]
    noise_samples: list[DataAuditGrantSample]


class GrantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_source_by_slug(self, slug: str) -> Source | None:
        return self.session.scalar(select(Source).where(Source.slug == slug))

    def list_sources(self, *, enabled_only: bool = False) -> list[Source]:
        query = select(Source).order_by(Source.slug)
        if enabled_only:
            query = query.where(Source.enabled.is_(True))
        return list(self.session.scalars(query))

    def get_grant_by_source_identity(
        self,
        *,
        source_id: uuid.UUID,
        source_url: str,
        source_record_id: str | None = None,
    ) -> Grant | None:
        if source_record_id:
            grant = self.session.scalar(
                select(Grant).where(
                    Grant.source_id == source_id,
                    Grant.source_record_id == source_record_id,
                )
            )
            if grant is not None:
                return grant
        return self.session.scalar(
            select(Grant).where(
                Grant.source_id == source_id,
                Grant.source_url == source_url,
            )
        )

    def upsert_source(
        self,
        *,
        slug: str,
        name: str,
        base_url: str,
        access_strategy: str | AccessStrategy,
        list_url: str | None = None,
        api_url: str | None = None,
        feed_url: str | None = None,
        sitemap_url: str | None = None,
        requires_browser: bool = False,
        enabled: bool = True,
        rate_limit_seconds: int = 5,
        notes: str | None = None,
        source_metadata: dict[str, Any] | None = None,
    ) -> Source:
        source = self.session.scalar(select(Source).where(Source.slug == slug))
        values = {
            "name": name,
            "base_url": base_url,
            "access_strategy": _enum_value(access_strategy),
            "list_url": list_url,
            "api_url": api_url,
            "feed_url": feed_url,
            "sitemap_url": sitemap_url,
            "requires_browser": requires_browser,
            "enabled": enabled,
            "rate_limit_seconds": rate_limit_seconds,
            "notes": notes,
            "source_metadata": source_metadata or {},
        }

        if source is None:
            source = Source(slug=slug, **values)
            self.session.add(source)
        else:
            for field, value in values.items():
                setattr(source, field, value)

        self.session.flush()
        return source

    def start_job(
        self,
        *,
        job_type: str | JobType,
        source_id: uuid.UUID | None = None,
        status: str | JobStatus = JobStatus.RUNNING,
        job_metadata: dict[str, Any] | None = None,
    ) -> JobRun:
        job = JobRun(
            job_type=_enum_value(job_type),
            source_id=source_id,
            status=_enum_value(status),
            job_metadata=job_metadata or {},
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, job_id: uuid.UUID) -> JobRun | None:
        return self.session.get(JobRun, job_id)

    def list_jobs(
        self,
        *,
        limit: int = 20,
        job_type: str | JobType | None = None,
        source_id: uuid.UUID | None = None,
    ) -> list[JobRun]:
        query = select(JobRun).order_by(JobRun.started_at.desc())
        if job_type is not None:
            query = query.where(JobRun.job_type == _enum_value(job_type))
        if source_id is not None:
            query = query.where(JobRun.source_id == source_id)
        return list(self.session.scalars(query.limit(limit)))

    def increment_job_counters(
        self,
        job: JobRun,
        *,
        processed: int = 0,
        created: int = 0,
        updated: int = 0,
        skipped: int = 0,
        failed: int = 0,
    ) -> JobRun:
        job.processed_count += processed
        job.created_count += created
        job.updated_count += updated
        job.skipped_count += skipped
        job.failed_count += failed
        self.session.flush()
        return job

    def finish_job_success(
        self,
        job: JobRun,
        *,
        job_metadata: dict[str, Any] | None = None,
    ) -> JobRun:
        job.status = JobStatus.SUCCESS.value
        job.finished_at = datetime.now(UTC)
        job.error_message = None
        job.job_metadata = _merge_metadata(job.job_metadata, job_metadata)
        self.session.flush()
        return job

    def finish_job_failed(
        self,
        job: JobRun,
        *,
        error_message: str,
        job_metadata: dict[str, Any] | None = None,
    ) -> JobRun:
        job.status = JobStatus.FAILED.value
        job.finished_at = datetime.now(UTC)
        job.error_message = error_message
        job.job_metadata = _merge_metadata(job.job_metadata, job_metadata)
        self.session.flush()
        return job

    def mark_job_partial(
        self,
        job: JobRun,
        *,
        error_message: str | None = None,
        job_metadata: dict[str, Any] | None = None,
    ) -> JobRun:
        job.status = JobStatus.PARTIAL.value
        job.finished_at = datetime.now(UTC)
        job.error_message = error_message
        job.job_metadata = _merge_metadata(job.job_metadata, job_metadata)
        self.session.flush()
        return job

    def save_raw_snapshot(
        self,
        *,
        source_id: uuid.UUID,
        source_url: str,
        content_hash: str,
        source_record_id: str | None = None,
        http_status: int | None = None,
        content_type: str | None = None,
        raw_title: str | None = None,
        raw_summary: str | None = None,
        raw_text: str | None = None,
        raw_html: str | None = None,
        raw_payload: dict[str, Any] | list[Any] | None = None,
        snapshot_metadata: dict[str, Any] | None = None,
    ) -> RawGrantSnapshot:
        snapshot = self.session.scalar(
            select(RawGrantSnapshot).where(
                RawGrantSnapshot.source_id == source_id,
                RawGrantSnapshot.source_url == source_url,
                RawGrantSnapshot.content_hash == content_hash,
            )
        )
        if snapshot is not None:
            return snapshot

        snapshot = RawGrantSnapshot(
            source_id=source_id,
            source_record_id=source_record_id,
            source_url=source_url,
            content_hash=content_hash,
            http_status=http_status,
            content_type=content_type,
            raw_title=raw_title,
            raw_summary=raw_summary,
            raw_text=raw_text,
            raw_html=raw_html,
            raw_payload=raw_payload,
            snapshot_metadata=snapshot_metadata or {},
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def get_discovered_item_by_identity(
        self,
        *,
        source_id: uuid.UUID,
        source_record_id: str | None = None,
        canonical_url: str | None = None,
        content_hash: str | None = None,
    ) -> DiscoveredGrantItem | None:
        if source_record_id:
            item = self.session.scalar(
                select(DiscoveredGrantItem).where(
                    DiscoveredGrantItem.source_id == source_id,
                    DiscoveredGrantItem.source_record_id == source_record_id,
                )
            )
            if item is not None:
                return item

        if canonical_url:
            item = self.session.scalar(
                select(DiscoveredGrantItem).where(
                    DiscoveredGrantItem.source_id == source_id,
                    DiscoveredGrantItem.canonical_url == canonical_url,
                )
            )
            if item is not None:
                return item

        if content_hash:
            return self.session.scalar(
                select(DiscoveredGrantItem).where(
                    DiscoveredGrantItem.source_id == source_id,
                    DiscoveredGrantItem.content_hash == content_hash,
                )
            )
        return None

    def upsert_discovered_item(
        self,
        *,
        source_id: uuid.UUID,
        source_slug: str,
        draft: DiscoveredGrantItemDraft,
    ) -> tuple[DiscoveredGrantItem, bool]:
        now = datetime.now(UTC)
        item = self.get_discovered_item_by_identity(
            source_id=source_id,
            source_record_id=draft.source_record_id,
            canonical_url=draft.canonical_url,
            content_hash=draft.content_hash,
        )
        was_created = item is None
        values = {
            "source_slug": source_slug,
            "source_url": draft.source_url,
            "canonical_url": draft.canonical_url,
            "source_record_id": draft.source_record_id,
            "title_hint": draft.title_hint,
            "summary_hint": draft.summary_hint,
            "published_at_hint": draft.published_at_hint,
            "deadline_hint": draft.deadline_hint,
            "listing_url": draft.listing_url,
            "listing_position": draft.listing_position,
            "last_seen_at": now,
            "content_hash": draft.content_hash,
            "discovery_metadata": draft.discovery_metadata,
        }

        if item is None:
            item = DiscoveredGrantItem(
                source_id=source_id,
                discovery_status=DiscoveryStatus.NEW.value,
                detail_fetch_status=DetailFetchStatus.NOT_FETCHED.value,
                **values,
            )
            self.session.add(item)
        else:
            values["discovery_status"] = DiscoveryStatus.KNOWN.value
            values["discovery_metadata"] = _merge_metadata(item.discovery_metadata, draft.discovery_metadata)
            for field, value in values.items():
                setattr(item, field, value)

        self.session.flush()
        return item, was_created

    def mark_discovered_detail_status(
        self,
        item: DiscoveredGrantItem,
        *,
        detail_fetch_status: str | DetailFetchStatus,
        metadata: dict[str, Any] | None = None,
    ) -> DiscoveredGrantItem:
        item.detail_fetch_status = _enum_value(detail_fetch_status)
        if metadata:
            item.discovery_metadata = _merge_metadata(item.discovery_metadata, metadata)
        self.session.flush()
        return item

    def get_grant_for_discovered_item(self, item: DiscoveredGrantItem) -> Grant | None:
        identity_conditions = []
        if item.source_record_id:
            identity_conditions.append(Grant.source_record_id == item.source_record_id)
        if item.canonical_url:
            identity_conditions.append(Grant.source_url == item.canonical_url)
        identity_conditions.append(Grant.source_url == item.source_url)

        return self.session.scalar(
            select(Grant)
            .where(
                Grant.source_id == item.source_id,
                or_(*identity_conditions),
            )
            .order_by(Grant.updated_at.desc())
            .limit(1)
        )

    def list_discovered_items_due_for_refresh(
        self,
        *,
        source_id: uuid.UUID,
        now: datetime | None = None,
        limit: int = 100,
        open_interval_days: int = 7,
        no_deadline_interval_days: int = 14,
    ) -> list[DiscoveredGrantItem]:
        now = now or datetime.now(UTC)
        open_cutoff = now - timedelta(days=open_interval_days)
        no_deadline_cutoff = now - timedelta(days=no_deadline_interval_days)
        identity_match = or_(
            and_(
                DiscoveredGrantItem.source_record_id.is_not(None),
                Grant.source_record_id == DiscoveredGrantItem.source_record_id,
            ),
            and_(
                DiscoveredGrantItem.canonical_url.is_not(None),
                Grant.source_url == DiscoveredGrantItem.canonical_url,
            ),
            Grant.source_url == DiscoveredGrantItem.source_url,
        )
        due_status = or_(
            and_(
                Grant.status == "open",
                Grant.deadline_at.is_not(None),
                Grant.updated_at <= open_cutoff,
            ),
            and_(
                Grant.status.in_(("open", "unknown")),
                Grant.deadline_at.is_(None),
                Grant.updated_at <= no_deadline_cutoff,
            ),
        )

        query = (
            select(DiscoveredGrantItem)
            .join(Grant, and_(Grant.source_id == DiscoveredGrantItem.source_id, identity_match))
            .where(
                DiscoveredGrantItem.source_id == source_id,
                due_status,
            )
            .order_by(Grant.updated_at.asc())
            .limit(limit)
        )
        return list(self.session.scalars(query))

    def search_source_report(self, *, source_slug: str | None = None) -> list[SearchSourceReportRow]:
        sources_query = select(Source).order_by(Source.slug)
        if source_slug is not None:
            sources_query = sources_query.where(Source.slug == source_slug)

        rows: list[SearchSourceReportRow] = []
        for source in self.session.scalars(sources_query):
            latest_job = self.session.scalar(
                select(JobRun)
                .where(
                    JobRun.source_id == source.id,
                    JobRun.job_type == JobType.INGESTION.value,
                )
                .order_by(JobRun.started_at.desc())
                .limit(1)
            )
            latest_metadata = latest_job.job_metadata if latest_job is not None else {}
            rows.append(
                SearchSourceReportRow(
                    source_slug=source.slug,
                    enabled=source.enabled,
                    discovered_total=self._count_discovered(source.id),
                    discovery_new=self._count_discovered(source.id, discovery_status=DiscoveryStatus.NEW.value),
                    discovery_known=self._count_discovered(source.id, discovery_status=DiscoveryStatus.KNOWN.value),
                    discovery_failed=self._count_discovered(source.id, discovery_status=DiscoveryStatus.FAILED.value),
                    detail_not_fetched=self._count_discovered(source.id, detail_fetch_status=DetailFetchStatus.NOT_FETCHED.value),
                    detail_fetched=self._count_discovered(source.id, detail_fetch_status=DetailFetchStatus.FETCHED.value),
                    detail_failed=self._count_discovered(source.id, detail_fetch_status=DetailFetchStatus.FAILED.value),
                    detail_skipped_known=self._count_discovered(
                        source.id,
                        detail_fetch_status=DetailFetchStatus.SKIPPED_KNOWN.value,
                    ),
                    grants_total=self._count_grants(source.id),
                    grants_open=self._count_grants(source.id, status="open"),
                    grants_unknown=self._count_grants(source.id, status="unknown"),
                    grants_manual_review=self._count_grants(source.id, needs_manual_review=True),
                    last_seen_at=self.session.scalar(
                        select(func.max(DiscoveredGrantItem.last_seen_at)).where(DiscoveredGrantItem.source_id == source.id)
                    ),
                    latest_job_status=latest_job.status if latest_job is not None else None,
                    latest_job_processed=latest_job.processed_count if latest_job is not None else 0,
                    latest_job_created=latest_job.created_count if latest_job is not None else 0,
                    latest_job_updated=latest_job.updated_count if latest_job is not None else 0,
                    latest_job_skipped=latest_job.skipped_count if latest_job is not None else 0,
                    latest_job_failed=latest_job.failed_count if latest_job is not None else 0,
                    latest_job_refresh_due=int(latest_metadata.get("refresh_due_count") or 0),
                    latest_job_refreshed_known=int(latest_metadata.get("refreshed_known_count") or 0),
                )
            )
        return rows

    def _count_discovered(
        self,
        source_id: uuid.UUID,
        *,
        discovery_status: str | None = None,
        detail_fetch_status: str | None = None,
    ) -> int:
        query = select(func.count(DiscoveredGrantItem.id)).where(DiscoveredGrantItem.source_id == source_id)
        if discovery_status is not None:
            query = query.where(DiscoveredGrantItem.discovery_status == discovery_status)
        if detail_fetch_status is not None:
            query = query.where(DiscoveredGrantItem.detail_fetch_status == detail_fetch_status)
        return int(self.session.scalar(query) or 0)

    def _count_grants(
        self,
        source_id: uuid.UUID,
        *,
        status: str | None = None,
        needs_manual_review: bool | None = None,
    ) -> int:
        query = select(func.count(Grant.id)).where(Grant.source_id == source_id)
        if status is not None:
            query = query.where(Grant.status == status)
        if needs_manual_review is not None:
            query = query.where(Grant.needs_manual_review.is_(needs_manual_review))
        return int(self.session.scalar(query) or 0)

    def data_audit_report(
        self,
        *,
        source_slug: str | None = None,
        sample_limit: int = 5,
    ) -> list[DataAuditSourceRow]:
        sources_query = select(Source).order_by(Source.slug)
        if source_slug is not None:
            sources_query = sources_query.where(Source.slug == source_slug)

        rows: list[DataAuditSourceRow] = []
        for source in self.session.scalars(sources_query):
            grants = list(
                self.session.scalars(
                    select(Grant)
                    .options(selectinload(Grant.source))
                    .where(Grant.source_id == source.id)
                    .order_by(Grant.updated_at.desc(), Grant.created_at.desc())
                )
            )
            total = len(grants)
            status_counts: dict[str, int] = {}
            manual_review_count = 0
            weak_count = 0
            noise_count = 0
            weak_samples: list[DataAuditGrantSample] = []
            noise_samples: list[DataAuditGrantSample] = []

            for grant in grants:
                status = grant.status or "unknown"
                status_counts[status] = status_counts.get(status, 0) + 1
                if grant.needs_manual_review:
                    manual_review_count += 1

                weak_reasons = self._data_audit_weak_reasons(grant)
                if weak_reasons:
                    weak_count += 1
                    if len(weak_samples) < sample_limit:
                        weak_samples.append(self._data_audit_sample(grant, weak_reasons))

                noise_reasons = self._data_audit_noise_reasons(grant)
                if noise_reasons:
                    noise_count += 1
                    if len(noise_samples) < sample_limit:
                        noise_samples.append(self._data_audit_sample(grant, noise_reasons))

            field_completeness = [
                DataAuditFieldCompleteness(
                    field_name=field_name,
                    populated_count=sum(1 for grant in grants if self._data_audit_field_populated(grant, field_name)),
                    missing_count=sum(1 for grant in grants if not self._data_audit_field_populated(grant, field_name)),
                    total_count=total,
                )
                for field_name in self._data_audit_field_names()
            ]
            rows.append(
                DataAuditSourceRow(
                    source_slug=source.slug,
                    grants_total=total,
                    status_counts=status_counts,
                    manual_review_count=manual_review_count,
                    field_completeness=field_completeness,
                    weak_record_count=weak_count,
                    noise_candidate_count=noise_count,
                    weak_samples=weak_samples,
                    noise_samples=noise_samples,
                )
            )
        return rows

    @staticmethod
    def _data_audit_field_names() -> tuple[str, ...]:
        return (
            "source_url",
            "title",
            "status_known",
            "summary_or_description",
            "deadline_at",
            "deadline_text",
            "funder_name",
            "funding_amount_text",
            "currency",
            "countries",
            "regions",
            "eligibility_text",
            "application_url",
            "published_at",
        )

    @staticmethod
    def _data_audit_field_populated(grant: Grant, field_name: str) -> bool:
        if field_name == "status_known":
            return grant.status in {"open", "closed"}
        if field_name == "summary_or_description":
            return bool((grant.summary or "").strip() or (grant.description_text or "").strip())
        if field_name in {"countries", "regions"}:
            return bool(getattr(grant, field_name) or [])
        value = getattr(grant, field_name)
        if isinstance(value, str):
            return bool(value.strip())
        return value is not None

    @staticmethod
    def _data_audit_weak_reasons(grant: Grant) -> list[str]:
        reasons: list[str] = []
        title = (grant.title or "").strip()
        source_url = (grant.source_url or "").strip()
        if len(title) < 8:
            reasons.append("weak_title")
        if not source_url.startswith("http"):
            reasons.append("missing_source_url")
        if grant.status not in {"open", "closed"}:
            reasons.append("status_unknown")
        if not ((grant.summary or "").strip() or (grant.description_text or "").strip()):
            reasons.append("missing_summary")
        if grant.deadline_at is None:
            reasons.append("missing_deadline")
        if not (grant.funder_name or "").strip():
            reasons.append("missing_funder")
        if not (grant.funding_amount_text or "").strip():
            reasons.append("missing_amount")
        if not (grant.currency or "").strip():
            reasons.append("missing_currency")
        if not (grant.countries or []) and not (grant.regions or []) and not (grant.geography_text or "").strip():
            reasons.append("missing_geography")
        if not (grant.eligibility_text or "").strip():
            reasons.append("missing_eligibility")
        if grant.needs_manual_review:
            reasons.append("needs_manual_review")
        if grant.extraction_confidence is not None and Decimal(str(grant.extraction_confidence)) < Decimal("0.5000"):
            reasons.append("low_extraction_confidence")
        return reasons

    @staticmethod
    def _data_audit_noise_reasons(grant: Grant) -> list[str]:
        title = (grant.title or "").lower()
        text = " ".join(
            part
            for part in (
                grant.title,
                grant.summary,
                grant.description_text,
                grant.opportunity_type,
                grant.support_type,
            )
            if part
        ).lower()
        reasons: list[str] = []
        terms = {
            "possible_digest": ("digest", "дайджест", "добірка", "opportunities currently open", "opportunities closing"),
            "possible_news": ("news", "новин", "підсумк", "відбулася", "долучився", "долучилась"),
            "possible_article": ("article", "стаття", "як використовувати", "guide", "гайд"),
            "possible_webinar": ("webinar", "вебінар"),
            "possible_event": ("event", "подія", "conference", "конференц", "воркшоп", "workshop"),
        }
        for reason, markers in terms.items():
            if any(marker in text for marker in markers):
                reasons.append(reason)

        training_title = any(marker in title for marker in ("тренінг", "training", "course", "курс", "семінар"))
        grant_title = any(marker in title for marker in ("grant", "грант", "конкурс", "call for proposals"))
        if training_title and not grant_title:
            reasons.append("possible_training_not_grant")

        if grant.opportunity_type in {"training", "tender"}:
            reasons.append(f"unsupported_opportunity_type:{grant.opportunity_type}")
        if grant.support_type in {"training", "procurement"}:
            reasons.append(f"unsupported_support_type:{grant.support_type}")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _data_audit_sample(grant: Grant, reasons: list[str]) -> DataAuditGrantSample:
        return DataAuditGrantSample(
            title=grant.title,
            status=grant.status,
            source_url=grant.source_url,
            reasons=reasons,
            manual_review_reason=grant.manual_review_reason,
        )

    def search_quality_gate_report(
        self,
        *,
        required_source_slugs: list[str],
        excluded_source_slugs: list[str] | None = None,
        required_count: int = 10,
        sample_limit: int = 10,
    ) -> list[SearchQualityGateRow]:
        excluded = set(excluded_source_slugs or [])
        source_slugs = sorted(set(required_source_slugs) | excluded)
        rows: list[SearchQualityGateRow] = []
        for slug in source_slugs:
            source = self.get_source_by_slug(slug)
            if source is None:
                rows.append(
                    SearchQualityGateRow(
                        source_slug=slug,
                        required=slug not in excluded,
                        required_count=required_count,
                        grants_total=0,
                        quality_approved_count=0,
                        rejected_count=0,
                        passed=False,
                        samples=[],
                    )
                )
                continue
            grants = list(
                self.session.scalars(
                    select(Grant)
                    .where(Grant.source_id == source.id)
                    .order_by(Grant.updated_at.desc(), Grant.created_at.desc())
                )
            )
            approved = [grant for grant in grants if self._is_quality_approved_grant(grant)]
            required = slug not in excluded
            rows.append(
                SearchQualityGateRow(
                    source_slug=slug,
                    required=required,
                    required_count=required_count,
                    grants_total=len(grants),
                    quality_approved_count=len(approved),
                    rejected_count=len(grants) - len(approved),
                    passed=(len(approved) >= required_count) if required else True,
                    samples=[
                        SearchQualityGrantSample(
                            title=grant.title,
                            status=grant.status,
                            deadline_text=grant.deadline_text,
                            funding_amount_text=grant.funding_amount_text,
                            source_url=grant.source_url,
                            needs_manual_review=grant.needs_manual_review,
                        )
                        for grant in approved[:sample_limit]
                    ],
                )
            )
        return rows

    @staticmethod
    def _is_quality_approved_grant(grant: Grant) -> bool:
        title = (grant.title or "").strip()
        source_url = (grant.source_url or "").strip()
        if len(title) < 8 or not source_url.startswith("http"):
            return False
        title_lower = title.lower()
        generic_titles = {
            "grant",
            "grants",
            "funding",
            "opportunity",
            "opportunities",
            "грант",
            "гранти",
            "конкурс",
            "можливості",
        }
        if title_lower in generic_titles:
            return False

        noise_title_terms = (
            "добірка",
            "дайджест",
            "підсумк",
            "вебінар",
            "запрошуємо на",
            "долучився",
            "долучилась",
            "відбулася",
            "воркшоп",
            "конференц",
            "презентац",
            "презентуємо",
            "стратегічна сесія",
            "оновлено інтерактивний",
            "як використовувати",
        )
        if any(term in title_lower for term in noise_title_terms):
            return False

        text_parts = [
            grant.title,
            grant.summary,
            grant.deadline_text,
            grant.funding_amount_text,
            grant.funder_name,
            grant.opportunity_type,
            grant.support_type,
            grant.program_name,
        ]
        text = " ".join(part for part in text_parts if part).lower()
        direct_title_terms = (
            "grant",
            "grants",
            "funding",
            "fund",
            "call for proposals",
            "call for applications",
            "open call",
            "applications open",
            "apply now",
            "cfa",
            "cfas",
            "rfp",
            "rfps",
            "award",
            "awards",
            "prize",
            "programme",
            "program",
            "грант",
            "грантов",
            "конкурс",
            "конкурсний",
            "фінанс",
            "відшкодуван",
            "компенсац",
            "ваучер",
            "субсид",
            "кредит",
            "прийом заяв",
            "подання заяв",
            "відбір",
        )
        structured_signal = bool(
            grant.deadline_at
            or grant.deadline_text
            or grant.funding_amount_text
            or grant.funder_name
            or grant.application_url
            or grant.documents
        )
        taxonomy_signal = bool(grant.topics or grant.applicant_types or grant.countries or grant.regions)
        title_keyword_signal = any(term in title_lower for term in direct_title_terms)
        summary_signal = any(
            term in (grant.summary or "").lower()
            for term in (
                "оголошує конкурс",
                "прийом заяв",
                "подати заявку",
                "call for proposals",
                "call for applications",
                "applications open",
            )
        )
        source_slug = grant.source.slug if grant.source is not None else None
        official_structured_source = source_slug in {"eu-funding", "diia-business", "grant-market", "grantforward"}
        keyword_signal = title_keyword_signal or summary_signal or official_structured_source
        return keyword_signal and (structured_signal or taxonomy_signal)

    def upsert_grant(
        self,
        *,
        source_id: uuid.UUID,
        source_url: str,
        title: str,
        status: str = "unknown",
        source_record_id: str | None = None,
        latest_raw_snapshot_id: uuid.UUID | None = None,
        **fields: Any,
    ) -> Grant:
        grant = None
        if source_record_id:
            grant = self.session.scalar(
                select(Grant).where(
                    Grant.source_id == source_id,
                    Grant.source_record_id == source_record_id,
                )
            )

        if grant is None:
            grant = self.session.scalar(
                select(Grant).where(
                    Grant.source_id == source_id,
                    Grant.source_url == source_url,
                )
            )

        values = {
            "source_url": source_url,
            "title": title,
            "status": status,
            "source_record_id": source_record_id,
            "latest_raw_snapshot_id": latest_raw_snapshot_id,
            **fields,
        }

        if grant is None:
            grant = Grant(source_id=source_id, **values)
            self.session.add(grant)
        else:
            for field, value in values.items():
                if not hasattr(grant, field):
                    raise ValueError(f"Unknown grant field: {field}")
                setattr(grant, field, value)

        self.session.flush()
        return grant

    def list_grants_for_feature_extraction(
        self,
        *,
        source_slug: str | None = None,
        limit: int = 100,
    ) -> list[Grant]:
        query = (
            select(Grant)
            .options(
                selectinload(Grant.source),
                selectinload(Grant.latest_raw_snapshot),
            )
            .order_by(Grant.updated_at.desc())
            .limit(limit)
        )
        if source_slug is not None:
            query = query.join(Source).where(Source.slug == source_slug)
        return list(self.session.scalars(query))

    def update_grant_features(self, grant: Grant, **fields: Any) -> Grant:
        for field, value in fields.items():
            if not hasattr(grant, field):
                raise ValueError(f"Unknown grant field: {field}")
            setattr(grant, field, value)
        self.session.flush()
        return grant

    def upsert_client_profile(
        self,
        *,
        slug: str,
        name: str,
        **fields: Any,
    ) -> ClientProfile:
        client = self.session.scalar(select(ClientProfile).where(ClientProfile.slug == slug))
        values = {"name": name, **fields}

        if client is None:
            client = ClientProfile(slug=slug, **values)
            self.session.add(client)
        else:
            for field, value in values.items():
                if not hasattr(client, field):
                    raise ValueError(f"Unknown client profile field: {field}")
                setattr(client, field, value)

        self.session.flush()
        return client

    def get_client_profile_by_slug(self, slug: str) -> ClientProfile | None:
        return self.session.scalar(select(ClientProfile).where(ClientProfile.slug == slug))

    def get_client_profile_by_name(self, name: str) -> ClientProfile | None:
        return self.session.scalar(select(ClientProfile).where(ClientProfile.name == name))

    def list_client_profiles(self, *, enabled_only: bool = True) -> list[ClientProfile]:
        query = select(ClientProfile).order_by(ClientProfile.name)
        if enabled_only:
            query = query.where(ClientProfile.enabled.is_(True))
        return list(self.session.scalars(query))

    def list_grants_for_matching(self, *, limit: int | None = None) -> list[Grant]:
        query = select(Grant).options(selectinload(Grant.source)).order_by(Grant.updated_at.desc())
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def list_grants_for_deduplication(
        self,
        *,
        source_slug: str | None = None,
        limit: int | None = None,
    ) -> list[Grant]:
        query = select(Grant).options(selectinload(Grant.source)).order_by(Grant.updated_at.desc(), Grant.created_at.desc())
        if source_slug is not None:
            query = query.join(Source).where(Source.slug == source_slug)
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def list_application_history_for_client(self, client_profile_id: uuid.UUID) -> list[ApplicationHistory]:
        query = (
            select(ApplicationHistory)
            .where(ApplicationHistory.client_profile_id == client_profile_id)
            .order_by(ApplicationHistory.application_date.desc().nullslast(), ApplicationHistory.created_at.desc())
        )
        return list(self.session.scalars(query))

    def list_grants_for_embedding(self, *, limit: int | None = None) -> list[Grant]:
        query = select(Grant).order_by(Grant.updated_at.desc())
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def list_client_profiles_for_embedding(self, *, enabled_only: bool = True, limit: int | None = None) -> list[ClientProfile]:
        query = select(ClientProfile).order_by(ClientProfile.name)
        if enabled_only:
            query = query.where(ClientProfile.enabled.is_(True))
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def list_application_history_for_embedding(self, *, limit: int | None = None) -> list[ApplicationHistory]:
        query = select(ApplicationHistory).order_by(ApplicationHistory.updated_at.desc())
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def save_application_history(
        self,
        *,
        client_profile_id: uuid.UUID,
        client_name: str,
        grant_title: str,
        result: str = "unknown",
        grant_id: uuid.UUID | None = None,
        similarity_weight: Decimal | float | int = Decimal("1"),
        **fields: Any,
    ) -> ApplicationHistory:
        history = ApplicationHistory(
            client_profile_id=client_profile_id,
            grant_id=grant_id,
            client_name=client_name,
            grant_title=grant_title,
            result=result,
            similarity_weight=Decimal(str(similarity_weight)),
            **fields,
        )
        self.session.add(history)
        self.session.flush()
        return history

    def upsert_application_history(
        self,
        *,
        client_profile_id: uuid.UUID,
        client_name: str,
        grant_title: str,
        result: str = "unknown",
        grant_id: uuid.UUID | None = None,
        similarity_weight: Decimal | float | int = Decimal("1"),
        grant_source: str | None = None,
        program_name: str | None = None,
        **fields: Any,
    ) -> ApplicationHistory:
        query = select(ApplicationHistory).where(
            ApplicationHistory.client_profile_id == client_profile_id,
            ApplicationHistory.grant_title == grant_title,
        )
        if grant_source is None:
            query = query.where(ApplicationHistory.grant_source.is_(None))
        else:
            query = query.where(ApplicationHistory.grant_source == grant_source)
        if program_name is None:
            query = query.where(ApplicationHistory.program_name.is_(None))
        else:
            query = query.where(ApplicationHistory.program_name == program_name)

        history = self.session.scalar(query)
        values = {
            "client_name": client_name,
            "grant_title": grant_title,
            "grant_source": grant_source,
            "program_name": program_name,
            "result": result,
            "grant_id": grant_id,
            "similarity_weight": Decimal(str(similarity_weight)),
            **fields,
        }

        if history is None:
            history = ApplicationHistory(client_profile_id=client_profile_id, **values)
            self.session.add(history)
        else:
            for field, value in values.items():
                if not hasattr(history, field):
                    raise ValueError(f"Unknown application history field: {field}")
                setattr(history, field, value)

        self.session.flush()
        return history

    def create_match_run(
        self,
        *,
        name: str | None = None,
        run_type: str = "manual",
        status: str = "pending",
        parameters: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> MatchRun:
        match_run = MatchRun(
            name=name,
            run_type=run_type,
            status=status,
            parameters=parameters or {},
            notes=notes,
        )
        self.session.add(match_run)
        self.session.flush()
        return match_run

    def get_match_run(self, match_run_id: uuid.UUID) -> MatchRun | None:
        return self.session.get(MatchRun, match_run_id)

    def latest_match_run(self) -> MatchRun | None:
        return self.session.scalar(select(MatchRun).order_by(MatchRun.started_at.desc()))

    def list_matches_for_explanation(
        self,
        *,
        match_run_id: uuid.UUID,
        limit: int = 20,
    ) -> list[GrantClientMatch]:
        query = (
            select(GrantClientMatch)
            .where(GrantClientMatch.match_run_id == match_run_id)
            .options(
                selectinload(GrantClientMatch.grant).selectinload(Grant.source),
                selectinload(GrantClientMatch.client_profile),
            )
            .order_by(GrantClientMatch.rank.asc().nullslast(), GrantClientMatch.score.desc())
            .limit(limit)
        )
        return list(self.session.scalars(query))

    def save_match_result(
        self,
        *,
        match_run_id: uuid.UUID,
        grant_id: uuid.UUID,
        client_profile_id: uuid.UUID,
        score: Decimal | float | int,
        **fields: Any,
    ) -> GrantClientMatch:
        match = self.session.scalar(
            select(GrantClientMatch).where(
                GrantClientMatch.match_run_id == match_run_id,
                GrantClientMatch.grant_id == grant_id,
                GrantClientMatch.client_profile_id == client_profile_id,
            )
        )
        values = {"score": Decimal(str(score)), **fields}

        if match is None:
            match = GrantClientMatch(
                match_run_id=match_run_id,
                grant_id=grant_id,
                client_profile_id=client_profile_id,
                **values,
            )
            self.session.add(match)
        else:
            for field, value in values.items():
                if not hasattr(match, field):
                    raise ValueError(f"Unknown match field: {field}")
                setattr(match, field, value)

        self.session.flush()
        return match

    def save_report(
        self,
        *,
        title: str,
        content: str,
        match_run_id: uuid.UUID | None = None,
        report_type: str = "daily",
        format: str = "markdown",
        summary: str | None = None,
        report_metadata: dict[str, Any] | None = None,
    ) -> Report:
        report = Report(
            match_run_id=match_run_id,
            title=title,
            report_type=report_type,
            format=format,
            summary=summary,
            content=content,
            report_metadata=report_metadata or {},
        )
        self.session.add(report)
        self.session.flush()
        return report
