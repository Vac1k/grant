from __future__ import annotations

import xml.etree.ElementTree as ET

from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.connectors.common import extract_filtered_links, parse_xml
from grant_tool.ingestion.types import ConnectorError, ConnectorResult, FetchedGrant, NormalizedGrantDraft
from grant_tool.ingestion.utils import (
    absolute_url,
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

    def run(self, *, limit: int) -> ConnectorResult:
        feed_url = self.source.feed_url or self.source.list_url
        if not feed_url:
            return ConnectorResult(
                source_slug=self.source_slug,
                errors=[ConnectorError(message="Source feed_url/list_url is not configured", stage="fetch_list")],
            )
        response = self.http.get(feed_url)
        items = self._parse_feed(response.text, limit=limit)
        if not items and self.source.list_url:
            listing = self.http.get(self.source.list_url)
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
        grants: list[FetchedGrant] = []
        errors: list[ConnectorError] = []
        for item in items:
            link = item["link"]
            try:
                detail = self.http.get(link)
                grants.append(
                    self._parse_detail(
                        feed_item=item,
                        detail_html=detail.text,
                        http_status=detail.status_code,
                        content_type=detail.content_type,
                    )
                )
            except Exception as exc:
                errors.append(ConnectorError(message=str(exc), source_url=link, stage="fetch_detail"))
                grants.append(self._from_feed_item(item, http_status=response.status_code, content_type=response.content_type))
        return ConnectorResult(source_slug=self.source_slug, grants=grants, errors=errors)

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
            language="uk",
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
            language="uk",
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
