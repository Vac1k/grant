from __future__ import annotations

from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.connectors.common import extract_filtered_links
from grant_tool.ingestion.hash import content_hash
from grant_tool.ingestion.types import (
    DiscoveredGrantItemDraft,
    DiscoveryMode,
    FetchedDetail,
    FetchedGrant,
    NormalizedGrantDraft,
)
from grant_tool.ingestion.utils import (
    canonicalize_url,
    clean_text,
    extract_deadline,
    extract_documents,
    extract_funding_text,
    soup_text,
    status_from_deadline,
)


class GurtConnector(BaseConnector):
    source_slug = "gurt"

    def discover(self, *, limit: int, mode: DiscoveryMode) -> list[DiscoveredGrantItemDraft]:
        if not self.source.list_url:
            raise ValueError("Source list_url is not configured")
        response = self.http.get(self.source.list_url)
        links = extract_filtered_links(
            base_url=self.source.base_url,
            html=response.text,
            include="/news/grants/",
            exclude_exact={self.source.list_url},
            limit=limit,
        )
        return [
            DiscoveredGrantItemDraft(
                source_url=source_url,
                canonical_url=canonicalize_url(source_url),
                source_record_id=source_url,
                title_hint=title_hint,
                listing_url=self.source.list_url,
                listing_position=position,
                content_hash=content_hash({"source_url": source_url, "title_hint": title_hint}),
                discovery_metadata={
                    "listing_url": self.source.list_url,
                    "http_status": response.status_code,
                    "content_type": response.content_type,
                },
            )
            for position, (source_url, title_hint) in enumerate(links, start=1)
        ]

    def fetch_detail(self, item: DiscoveredGrantItemDraft) -> FetchedDetail:
        detail = self.http.get(item.source_url)
        return FetchedDetail(
            source_url=item.source_url,
            raw_html=detail.text,
            http_status=detail.status_code,
            content_type=detail.content_type,
            metadata={"source": self.source_slug, "detail_url": item.source_url},
        )

    def normalize(self, item: DiscoveredGrantItemDraft, detail: FetchedDetail) -> NormalizedGrantDraft:
        if not detail.raw_html:
            raise ValueError("GURT detail does not contain HTML")
        return self._parse_detail(
            source_url=item.source_url,
            title_hint=item.title_hint or "Untitled GURT grant",
            detail_html=detail.raw_html,
            http_status=detail.http_status or 200,
            content_type=detail.content_type,
        ).normalized

    def _parse_detail(
        self,
        *,
        source_url: str,
        title_hint: str,
        detail_html: str,
        http_status: int,
        content_type: str | None,
    ) -> FetchedGrant:
        text = soup_text(detail_html)
        title = self._extract_title(detail_html) or title_hint
        deadline_at, deadline_text = extract_deadline(text)
        normalized = NormalizedGrantDraft(
            source_url=source_url,
            source_record_id=source_url,
            title=title,
            summary=self._summary(text),
            description_text=text,
            deadline_at=deadline_at,
            deadline_text=deadline_text,
            status=status_from_deadline(deadline_at),
            opportunity_type="grant",
            support_type="grant",
            funding_amount_text=extract_funding_text(text),
            documents=extract_documents(self.source.base_url, detail_html),
            source_metadata={"detail_url": source_url},
            extraction_metadata={"connector": self.source_slug},
        )
        return FetchedGrant(
            normalized=normalized,
            raw_html=detail_html,
            raw_text=text,
            raw_title=title,
            raw_summary=normalized.summary,
            http_status=http_status,
            content_type=content_type,
            snapshot_metadata={"source": self.source_slug, "detail_url": source_url},
        )

    @staticmethod
    def _extract_title(html: str) -> str | None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for selector in ("h1", "h2", "title"):
            node = soup.select_one(selector)
            if node:
                title = clean_text(node.get_text(" ", strip=True))
                if title:
                    return title
        return None

    @staticmethod
    def _summary(text: str | None) -> str | None:
        if not text:
            return None
        return clean_text(text[:500])
