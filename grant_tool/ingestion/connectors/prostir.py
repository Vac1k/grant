from __future__ import annotations

import xml.etree.ElementTree as ET

from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.connectors.common import extract_filtered_links, parse_xml
from grant_tool.ingestion.hash import content_hash
from grant_tool.ingestion.types import (
    DiscoveredGrantItemDraft,
    DiscoveryMode,
    FetchedDetail,
    FetchedGrant,
    NormalizedGrantDraft,
)
from grant_tool.ingestion.utils import (
    absolute_url,
    canonicalize_url,
    clean_text,
    extract_deadline,
    extract_documents,
    extract_funding_text,
    parse_datetime,
    soup_text,
    status_from_deadline,
)


class ProstirConnector(BaseConnector):
    source_slug = "prostir"

    def discover(self, *, limit: int, mode: DiscoveryMode) -> list[DiscoveredGrantItemDraft]:
        feed_url = self.source.feed_url or self.source.list_url
        if not feed_url:
            raise ValueError("Source feed_url/list_url is not configured")
        response = self.http.get(feed_url)
        items = self._parse_feed(response.text, limit=limit)
        listing_url = feed_url
        if not items and self.source.list_url:
            listing = self.http.get(self.source.list_url)
            listing_url = self.source.list_url
            items = [
                {
                    "title": title,
                    "link": url,
                    "guid": url,
                    "pub_date": None,
                    "description": None,
                }
                for url, title in extract_filtered_links(
                    base_url=self.source.base_url,
                    html=listing.text,
                    include="?grants=",
                    exclude_exact={self.source.list_url},
                    limit=limit,
                )
            ]
        discovered: list[DiscoveredGrantItemDraft] = []
        for position, item in enumerate(items[:limit], start=1):
            link = item["link"]
            if not link:
                continue
            discovered.append(
                DiscoveredGrantItemDraft(
                    source_url=link,
                    canonical_url=canonicalize_url(link),
                    source_record_id=item.get("guid") or link,
                    title_hint=item.get("title"),
                    summary_hint=item.get("description"),
                    published_at_hint=parse_datetime(item.get("pub_date")),
                    listing_url=listing_url,
                    listing_position=position,
                    content_hash=content_hash(item),
                    discovery_metadata={
                        "feed_item": item,
                        "feed_url": feed_url,
                        "listing_url": listing_url,
                        "http_status": response.status_code,
                        "content_type": response.content_type,
                    },
                )
            )
        return discovered

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
        feed_item = item.discovery_metadata.get("feed_item")
        if not isinstance(feed_item, dict):
            raise ValueError("Prostir discovery item does not contain feed_item metadata")
        if not detail.raw_html:
            return self._from_feed_item(
                feed_item,
                http_status=detail.http_status,
                content_type=detail.content_type,
            ).normalized
        return self._parse_detail(
            feed_item=feed_item,
            detail_html=detail.raw_html,
            http_status=detail.http_status or 200,
            content_type=detail.content_type,
        ).normalized

    def _parse_feed(self, xml_text: str, *, limit: int) -> list[dict[str, str | None]]:
        root = parse_xml(xml_text)
        items: list[dict[str, str | None]] = []
        for item in root.findall(".//item"):
            parsed = self._parse_rss_item(item)
            if parsed["title"] and parsed["link"]:
                items.append(parsed)
            if len(items) >= limit:
                break
        return items

    @staticmethod
    def _parse_rss_item(item: ET.Element) -> dict[str, str | None]:
        def text(name: str) -> str | None:
            node = item.find(name)
            return clean_text(node.text if node is not None else None)

        return {
            "title": text("title"),
            "link": text("link"),
            "guid": text("guid"),
            "pub_date": text("pubDate"),
            "description": text("description"),
        }

    def _from_feed_item(
        self,
        feed_item: dict[str, str | None],
        *,
        http_status: int | None,
        content_type: str | None,
    ) -> FetchedGrant:
        source_url = feed_item["link"] or self.source.base_url
        title = feed_item["title"] or "Untitled Prostir opportunity"
        summary = feed_item.get("description")
        normalized = NormalizedGrantDraft(
            source_url=source_url,
            source_record_id=feed_item.get("guid") or source_url,
            title=title,
            summary=summary,
            description_text=summary,
            published_at=parse_datetime(feed_item.get("pub_date")),
            status="unknown",
            source_metadata={"feed_item": feed_item},
            extraction_metadata={"connector": self.source_slug, "detail_fetch": "failed"},
        )
        return FetchedGrant(
            normalized=normalized,
            raw_payload=feed_item,
            raw_title=title,
            raw_summary=summary,
            http_status=http_status,
            content_type=content_type,
            snapshot_metadata={"source": self.source_slug, "partial": True},
        )

    def _parse_detail(
        self,
        *,
        feed_item: dict[str, str | None],
        detail_html: str,
        http_status: int,
        content_type: str | None,
    ) -> FetchedGrant:
        source_url = feed_item["link"] or self.source.base_url
        title = feed_item["title"] or "Untitled Prostir opportunity"
        text = soup_text(detail_html)
        deadline_at, deadline_text = extract_deadline(text)
        documents = extract_documents(self.source.base_url, detail_html)
        funding_text = extract_funding_text(text)
        normalized = NormalizedGrantDraft(
            source_url=source_url,
            source_record_id=feed_item.get("guid") or source_url,
            title=title,
            summary=feed_item.get("description"),
            description_text=text,
            published_at=parse_datetime(feed_item.get("pub_date")),
            deadline_at=deadline_at,
            deadline_text=deadline_text,
            status=status_from_deadline(deadline_at),
            opportunity_type="grant",
            support_type="grant",
            funding_amount_text=funding_text,
            documents=documents,
            source_metadata={"feed_item": feed_item},
            extraction_metadata={"connector": self.source_slug},
        )
        return FetchedGrant(
            normalized=normalized,
            raw_payload=feed_item,
            raw_html=detail_html,
            raw_text=text,
            raw_title=title,
            raw_summary=feed_item.get("description"),
            http_status=http_status,
            content_type=content_type,
            snapshot_metadata={"source": self.source_slug, "detail_url": absolute_url(self.source.base_url, source_url)},
        )
