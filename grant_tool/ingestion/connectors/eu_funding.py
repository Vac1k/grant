from __future__ import annotations

import json
from typing import Any

from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.hash import content_hash
from grant_tool.ingestion.types import (
    DiscoveredGrantItemDraft,
    DiscoveryMode,
    FetchedDetail,
    FetchedGrant,
    NormalizedGrantDraft,
)
from grant_tool.ingestion.utils import absolute_url, canonicalize_url, first_text, list_text, parse_datetime


class EUFundingConnector(BaseConnector):
    source_slug = "eu-funding"

    def discover(self, *, limit: int, mode: DiscoveryMode) -> list[DiscoveredGrantItemDraft]:
        if not self.source.api_url:
            raise ValueError("Source api_url is not configured")

        query = {
            "bool": {
                "must": [
                    {"terms": {"type": ["1", "2"]}},
                    {"term": {"programmePeriod": "2021 - 2027"}},
                ]
            }
        }
        sort = {"field": "sortStatus", "order": "ASC"}
        response = self.http.post(
            self.source.api_url,
            params={"apiKey": "SEDIA", "text": "***", "pageSize": str(limit), "pageNumber": "1"},
            files={
                "query": ("blob", json.dumps(query), "application/json"),
                "languages": ("blob", json.dumps(["en"]), "application/json"),
                "sort": ("blob", json.dumps(sort), "application/json"),
            },
        )
        payload = response.json_data
        if not isinstance(payload, dict):
            try:
                payload = json.loads(response.text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"EU API did not return JSON: {exc}") from exc

        results = payload.get("results") or payload.get("items") or []
        discovered: list[DiscoveredGrantItemDraft] = []
        for position, item in enumerate(results[:limit], start=1):
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            title = first_text(item.get("content")) or first_text(metadata.get("title")) or "Untitled EU opportunity"
            source_url = (
                absolute_url(self.source.base_url, first_text(item.get("url")))
                or absolute_url(self.source.base_url, first_text(metadata.get("url")))
                or self.source.base_url
            )
            source_record_id = (
                first_text(item.get("id"))
                or first_text(metadata.get("identifier"))
                or first_text(metadata.get("topicIdentifier"))
                or first_text(metadata.get("reference"))
            )
            discovered.append(
                DiscoveredGrantItemDraft(
                    source_url=source_url,
                    canonical_url=canonicalize_url(source_url),
                    source_record_id=source_record_id,
                    title_hint=title,
                    summary_hint=first_text(item.get("summary")) or first_text(metadata.get("summary")),
                    deadline_hint=first_text(metadata.get("deadlineDate")) or first_text(metadata.get("deadline")),
                    listing_url=self.source.api_url,
                    listing_position=position,
                    content_hash=content_hash(item),
                    discovery_metadata={
                        "api_url": self.source.api_url,
                        "http_status": response.status_code,
                        "content_type": response.content_type,
                        "raw_item": item,
                    },
                )
            )

        return discovered

    def fetch_detail(self, item: DiscoveredGrantItemDraft) -> FetchedDetail:
        raw_item = item.discovery_metadata.get("raw_item")
        if not isinstance(raw_item, dict):
            raise ValueError("EU discovery item does not contain raw_item metadata")
        return FetchedDetail(
            source_url=item.source_url,
            raw_payload=raw_item,
            http_status=item.discovery_metadata.get("http_status"),
            content_type=item.discovery_metadata.get("content_type"),
            metadata={"source": self.source_slug, "api_url": self.source.api_url},
        )

    def normalize(self, item: DiscoveredGrantItemDraft, detail: FetchedDetail) -> NormalizedGrantDraft:
        if not isinstance(detail.raw_payload, dict):
            raise ValueError("EU detail payload is not an object")
        return self._parse_item(
            detail.raw_payload,
            response_status=detail.http_status or 200,
            content_type=detail.content_type,
        ).normalized

    def _parse_item(
        self,
        item: dict[str, Any],
        *,
        response_status: int,
        content_type: str | None,
    ) -> FetchedGrant:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        title = first_text(item.get("content")) or first_text(metadata.get("title")) or "Untitled EU opportunity"
        source_url = (
            absolute_url(self.source.base_url, first_text(item.get("url")))
            or absolute_url(self.source.base_url, first_text(metadata.get("url")))
            or self.source.base_url
        )
        source_record_id = (
            first_text(item.get("id"))
            or first_text(metadata.get("identifier"))
            or first_text(metadata.get("topicIdentifier"))
            or first_text(metadata.get("reference"))
        )
        keywords = list_text(metadata.get("keywords"))
        topics = keywords[:]
        deadline_text = first_text(metadata.get("deadlineDate")) or first_text(metadata.get("deadline"))
        normalized = NormalizedGrantDraft(
            source_url=source_url,
            source_record_id=source_record_id,
            title=title,
            summary=first_text(item.get("summary")) or first_text(metadata.get("summary")),
            description_text=first_text(metadata.get("description")) or first_text(item.get("description")),
            status=first_text(metadata.get("status")) or "unknown",
            language="en",
            opens_at=parse_datetime(first_text(metadata.get("openingDate"))),
            deadline_at=parse_datetime(deadline_text),
            deadline_text=deadline_text,
            program_name=first_text(metadata.get("frameworkProgramme")) or first_text(metadata.get("programme")),
            funder_name="European Commission",
            opportunity_type="grant",
            support_type=first_text(metadata.get("type")) or "grant",
            funding_amount_text=first_text(metadata.get("budgetOverview")) or first_text(metadata.get("budget")),
            topics=topics,
            keywords=keywords,
            source_metadata={"eu_metadata": metadata},
            extraction_metadata={"connector": self.source_slug},
        )
        return FetchedGrant(
            normalized=normalized,
            raw_payload=item,
            raw_title=title,
            raw_summary=normalized.summary,
            http_status=response_status,
            content_type=content_type,
            snapshot_metadata={"source": self.source_slug, "api_url": self.source.api_url},
        )
