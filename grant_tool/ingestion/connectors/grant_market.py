from __future__ import annotations

import re

from bs4 import BeautifulSoup

from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.connectors.common import parse_sitemap_urls
from grant_tool.ingestion.hash import content_hash
from grant_tool.ingestion.types import (
    DiscoveredGrantItemDraft,
    DiscoveryMode,
    FetchedDetail,
    NormalizedGrantDraft,
)
from grant_tool.ingestion.utils import (
    canonicalize_url,
    clean_text,
    extract_deadline,
    extract_documents,
    extract_funding_text,
    parse_datetime,
    soup_text,
    status_from_deadline,
)


class GrantMarketConnector(BaseConnector):
    source_slug = "grant-market"

    def discover(self, *, limit: int, mode: DiscoveryMode) -> list[DiscoveredGrantItemDraft]:
        if not self.source.sitemap_url:
            raise ValueError("Source sitemap_url is not configured")
        response = self.http.get(self.source.sitemap_url)
        urls = parse_sitemap_urls(response.text, contains="/opp/", limit=limit)
        return [
            DiscoveredGrantItemDraft(
                source_url=url,
                canonical_url=canonicalize_url(url),
                source_record_id=canonicalize_url(url),
                title_hint=self._title_from_url(url),
                listing_url=self.source.sitemap_url,
                listing_position=position,
                content_hash=content_hash({"source": self.source_slug, "url": canonicalize_url(url)}),
                discovery_metadata={
                    "discovery_method": "sitemap",
                    "sitemap_url": self.source.sitemap_url,
                    "http_status": response.status_code,
                    "content_type": response.content_type,
                    "quality_level": "high",
                    "quality_reasons": ["direct_opportunity_url", "sitemap_opp_path"],
                    "is_probably_grant": True,
                    "is_probably_grant_reason": "sitemap URL contains /opp/",
                    "status_hint": "unknown",
                    "deadline_hint_source": "none",
                    "requires_manual_review": False,
                    "manual_review_reason": None,
                },
            )
            for position, url in enumerate(urls, start=1)
        ]

    def fetch_detail(self, item: DiscoveredGrantItemDraft) -> FetchedDetail:
        detail = self.http.get(item.source_url)
        return FetchedDetail(
            source_url=item.source_url,
            raw_html=detail.text,
            raw_text=soup_text(detail.text),
            http_status=detail.status_code,
            content_type=detail.content_type,
            metadata={"source": self.source_slug, "detail_url": item.source_url},
        )

    def normalize(self, item: DiscoveredGrantItemDraft, detail: FetchedDetail) -> NormalizedGrantDraft:
        if not detail.raw_html:
            raise ValueError("Grant Market detail does not contain HTML")
        soup = BeautifulSoup(detail.raw_html, "html.parser")
        text = detail.raw_text or soup_text(detail.raw_html) or ""
        deadline_at, deadline_text = extract_deadline(text)
        published_at = parse_datetime(self._meta_content(soup, "article:published_time")) or item.published_at_hint
        summary = self._meta_content(soup, "og:description") or self._meta_content(soup, "description")
        title = self._clean_title(
            self._meta_content(soup, "og:title")
            or self._selector_text(soup, "h1")
            or self._selector_text(soup, "title")
            or item.title_hint
            or "Untitled Grant Market opportunity"
        )
        return NormalizedGrantDraft(
            source_url=item.source_url,
            source_record_id=item.source_record_id,
            title=title,
            summary=summary or self._summary(text),
            description_text=text or None,
            published_at=published_at,
            deadline_at=deadline_at,
            deadline_text=deadline_text or item.deadline_hint,
            status=status_from_deadline(deadline_at),
            opportunity_type="grant",
            support_type="grant",
            funding_amount_text=extract_funding_text(text),
            documents=extract_documents(self.source.base_url, detail.raw_html),
            source_metadata={
                "source": self.source_slug,
                "discovery_method": item.discovery_metadata.get("discovery_method"),
                "quality_level": item.discovery_metadata.get("quality_level"),
                "quality_reasons": item.discovery_metadata.get("quality_reasons", []),
            },
        )

    @staticmethod
    def _title_from_url(url: str) -> str | None:
        slug = url.rstrip("/").split("/")[-1]
        if not slug:
            return None
        return clean_text(slug.replace("-", " ").replace("_", " ").title())

    @staticmethod
    def _meta_content(soup: BeautifulSoup, key: str) -> str | None:
        for node in soup.find_all("meta"):
            if node.get("property") == key or node.get("name") == key:
                return clean_text(node.get("content"))
        return None

    @staticmethod
    def _selector_text(soup: BeautifulSoup, selector: str) -> str | None:
        node = soup.select_one(selector)
        return clean_text(node.get_text(" ", strip=True) if node else None)

    @staticmethod
    def _clean_title(title: str) -> str:
        cleaned = clean_text(title) or "Untitled Grant Market opportunity"
        return re.sub(r"\s*\|\s*Grant Market\s*$", "", cleaned).strip() or cleaned

    @staticmethod
    def _summary(text: str | None) -> str | None:
        cleaned = clean_text(text)
        if not cleaned:
            return None
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        return clean_text(" ".join(sentences[:2])) or cleaned[:280]
