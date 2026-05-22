from __future__ import annotations

from abc import ABC, abstractmethod

from grant_tool.db.models import Source
from grant_tool.ingestion.http import HttpClient
from grant_tool.ingestion.types import (
    ConnectorError,
    ConnectorResult,
    DiscoveredGrantItemDraft,
    DiscoveryMode,
    FetchedDetail,
    FetchedGrant,
    NormalizedGrantDraft,
)


class BaseConnector(ABC):
    source_slug: str

    def __init__(self, *, source: Source, http_client: HttpClient) -> None:
        self.source = source
        self.http = http_client

    def run(self, *, limit: int, mode: DiscoveryMode | str = DiscoveryMode.BACKFILL) -> ConnectorResult:
        parsed_mode = DiscoveryMode(mode)
        errors: list[ConnectorError] = []
        try:
            discovered_items = self.discover(limit=limit, mode=parsed_mode)
        except Exception as exc:
            source_url = self.source.list_url or self.source.feed_url or self.source.api_url or self.source.base_url
            return ConnectorResult(
                source_slug=self.source_slug,
                errors=[ConnectorError(message=str(exc), source_url=source_url, stage="discover")],
            )

        grants: list[FetchedGrant] = []
        for item in discovered_items:
            try:
                detail = self.fetch_detail(item)
                normalized = self.normalize(item, detail)
                grants.append(self.to_fetched_grant(item, detail, normalized))
            except Exception as exc:
                errors.append(
                    ConnectorError(
                        message=str(exc),
                        source_url=item.source_url,
                        stage="fetch_detail",
                        metadata=item.identity_metadata(),
                    )
                )

        return ConnectorResult(source_slug=self.source_slug, grants=grants, errors=errors)

    @abstractmethod
    def discover(self, *, limit: int, mode: DiscoveryMode) -> list[DiscoveredGrantItemDraft]:
        raise NotImplementedError

    @abstractmethod
    def fetch_detail(self, item: DiscoveredGrantItemDraft) -> FetchedDetail:
        raise NotImplementedError

    @abstractmethod
    def normalize(self, item: DiscoveredGrantItemDraft, detail: FetchedDetail) -> NormalizedGrantDraft:
        raise NotImplementedError

    def to_fetched_grant(
        self,
        item: DiscoveredGrantItemDraft,
        detail: FetchedDetail,
        normalized: NormalizedGrantDraft,
    ) -> FetchedGrant:
        snapshot_metadata = {
            "source": self.source_slug,
            "discovery": item.identity_metadata(),
            **detail.metadata,
        }
        return FetchedGrant(
            normalized=normalized,
            raw_payload=detail.raw_payload,
            raw_html=detail.raw_html,
            raw_text=detail.raw_text,
            raw_title=item.title_hint or normalized.title,
            raw_summary=item.summary_hint or normalized.summary,
            http_status=detail.http_status,
            content_type=detail.content_type,
            snapshot_metadata=snapshot_metadata,
        )
