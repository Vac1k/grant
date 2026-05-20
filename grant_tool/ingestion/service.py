from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from grant_tool.config import get_settings
from grant_tool.db.models import JobRun, JobType
from grant_tool.db.repositories import GrantRepository
from grant_tool.extraction import FeatureExtractionService
from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.hash import content_hash
from grant_tool.ingestion.http import HttpClient
from grant_tool.ingestion.types import ConnectorError, FetchedGrant


@dataclass(slots=True)
class IngestionSummary:
    job: JobRun
    source_slug: str
    status: str
    processed_count: int
    created_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    errors: list[ConnectorError]


class IngestionService:
    def __init__(
        self,
        *,
        repository: GrantRepository,
        connector_classes: dict[str, type[BaseConnector]],
        http_client_factory: Callable[[float], HttpClient] | None = None,
        feature_extractor: FeatureExtractionService | None = None,
    ) -> None:
        self.repository = repository
        self.connector_classes = connector_classes
        self.http_client_factory = http_client_factory
        self.feature_extractor = feature_extractor or FeatureExtractionService()

    def run_source(self, source_slug: str, *, limit: int = 20) -> IngestionSummary:
        source = self.repository.get_source_by_slug(source_slug)
        if source is None:
            raise ValueError(f"Unknown source: {source_slug}. Run grant-tool seed-sources first.")
        connector_class = self.connector_classes.get(source_slug)
        if connector_class is None:
            raise ValueError(f"No connector registered for source: {source_slug}")

        job = self.repository.start_job(
            job_type=JobType.INGESTION,
            source_id=source.id,
            job_metadata={"source_slug": source.slug, "limit": limit},
        )
        errors: list[ConnectorError] = []
        settings = get_settings()
        if self.http_client_factory:
            http_client = self.http_client_factory(source.rate_limit_seconds)
        else:
            http_client = HttpClient(
                user_agent=settings.http_user_agent,
                rate_limit_seconds=source.rate_limit_seconds,
            )

        try:
            connector = connector_class(source=source, http_client=http_client)
            result = connector.run(limit=limit)
            errors.extend(result.errors)
            for fetched_grant in result.grants:
                try:
                    was_created = self._save_fetched_grant(fetched_grant, source_id=source.id, source_slug=source.slug)
                    if was_created:
                        self.repository.increment_job_counters(job, processed=1, created=1)
                    else:
                        self.repository.increment_job_counters(job, processed=1, updated=1)
                except Exception as exc:
                    errors.append(
                        ConnectorError(
                            message=str(exc),
                            source_url=fetched_grant.normalized.source_url,
                            stage="save",
                        )
                    )
                    self.repository.increment_job_counters(job, processed=1, failed=1)

            metadata: dict[str, Any] = {
                "source_slug": source.slug,
                "limit": limit,
                "connector_error_count": len(errors),
                "connector_errors": [self._error_to_dict(error) for error in errors[:20]],
            }
            if errors:
                self.repository.mark_job_partial(
                    job,
                    error_message=f"{len(errors)} connector/save errors",
                    job_metadata=metadata,
                )
            else:
                self.repository.finish_job_success(job, job_metadata=metadata)
        except Exception as exc:
            self.repository.finish_job_failed(job, error_message=str(exc))
            raise
        finally:
            http_client.close()

        return IngestionSummary(
            job=job,
            source_slug=source.slug,
            status=job.status,
            processed_count=job.processed_count,
            created_count=job.created_count,
            updated_count=job.updated_count,
            skipped_count=job.skipped_count,
            failed_count=job.failed_count,
            errors=errors,
        )

    def _save_fetched_grant(self, fetched_grant: FetchedGrant, *, source_id: Any, source_slug: str | None = None) -> bool:
        fetched_grant = self.feature_extractor.enrich_fetched_grant(fetched_grant, source_slug=source_slug)
        normalized = fetched_grant.normalized
        existing = self.repository.get_grant_by_source_identity(
            source_id=source_id,
            source_url=normalized.source_url,
            source_record_id=normalized.source_record_id,
        )
        raw_content = {
            "payload": fetched_grant.raw_payload,
            "html": fetched_grant.raw_html,
            "text": fetched_grant.raw_text,
            "source_url": normalized.source_url,
        }
        snapshot = self.repository.save_raw_snapshot(
            source_id=source_id,
            source_record_id=normalized.source_record_id,
            source_url=normalized.source_url,
            content_hash=content_hash(raw_content),
            http_status=fetched_grant.http_status,
            content_type=fetched_grant.content_type,
            raw_title=fetched_grant.raw_title or normalized.title,
            raw_summary=fetched_grant.raw_summary or normalized.summary,
            raw_text=fetched_grant.raw_text,
            raw_html=fetched_grant.raw_html,
            raw_payload=fetched_grant.raw_payload,
            snapshot_metadata=fetched_grant.snapshot_metadata,
        )
        self.repository.upsert_grant(
            source_id=source_id,
            source_record_id=normalized.source_record_id,
            source_url=normalized.source_url,
            latest_raw_snapshot_id=snapshot.id,
            title=normalized.title,
            status=normalized.status,
            **normalized.to_grant_fields(),
        )
        return existing is None

    @staticmethod
    def _error_to_dict(error: ConnectorError) -> dict[str, Any]:
        return {
            "message": error.message,
            "source_url": error.source_url,
            "stage": error.stage,
            "metadata": error.metadata,
        }
