from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, ClassVar

from bs4 import BeautifulSoup

from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.connectors.common import parse_xml
from grant_tool.ingestion.hash import content_hash
from grant_tool.ingestion.types import (
    DiscoveredGrantItemDraft,
    DiscoveryMode,
    FetchedDetail,
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


class WordPressGrantConnector(BaseConnector):
    search_terms: ClassVar[tuple[str, ...]] = ("grant",)
    grant_keywords: ClassVar[tuple[str, ...]] = (
        "grant",
        "grants",
        "funding",
        "call",
        "competition",
        "opportunity",
        "грант",
        "гранти",
        "конкурс",
        "конкурси",
        "фінансування",
        "підтримка",
        "можливості",
    )
    language: ClassVar[str | None] = None
    default_quality_level: ClassVar[str] = "medium"
    default_quality_reasons: ClassVar[tuple[str, ...]] = ()
    requires_manual_review_by_default: ClassVar[bool] = False
    manual_review_reason: ClassVar[str | None] = None

    def discover(self, *, limit: int, mode: DiscoveryMode) -> list[DiscoveredGrantItemDraft]:
        api_url = self._posts_api_url()
        discovered: list[DiscoveredGrantItemDraft] = []
        seen: set[str] = set()
        last_response_status: int | None = None
        last_content_type: str | None = None
        wp_rest_errors: list[str] = []

        for search_term in self._search_terms():
            if len(discovered) >= limit:
                break
            per_page = min(max(limit, 1), 50)
            try:
                response = self.http.get(
                    api_url,
                    params={
                        "per_page": per_page,
                        "search": search_term,
                        "orderby": "date",
                        "order": "desc",
                    },
                )
                last_response_status = response.status_code
                last_content_type = response.content_type
                posts = self._json_list(response)
            except Exception as exc:
                wp_rest_errors.append(str(exc))
                continue
            for post in posts:
                if len(discovered) >= limit:
                    break
                if not isinstance(post, dict) or not self._is_grant_like(post):
                    continue
                source_url = self._post_url(post)
                if not source_url:
                    continue
                identity = str(post.get("id") or "").strip() or source_url
                if identity in seen:
                    continue
                seen.add(identity)
                discovered.append(
                    DiscoveredGrantItemDraft(
                        source_url=source_url,
                        canonical_url=canonicalize_url(source_url),
                        source_record_id=str(post.get("id")) if post.get("id") is not None else None,
                        title_hint=self._rendered_text(post.get("title")),
                        summary_hint=self._rendered_text(post.get("excerpt")),
                        published_at_hint=parse_datetime(str(post.get("date_gmt") or post.get("date") or "")),
                        deadline_hint=self._deadline_hint(post),
                        listing_url=api_url,
                        listing_position=len(discovered) + 1,
                        content_hash=content_hash(post),
                        discovery_metadata={
                            "discovery_method": "wp_rest",
                            "api_url": api_url,
                            "search_term": search_term,
                            "http_status": response.status_code,
                            "content_type": response.content_type,
                            "quality_level": self.default_quality_level,
                            "quality_reasons": list(self.default_quality_reasons),
                            "is_probably_grant": True,
                            "is_probably_grant_reason": "wp_search_or_keyword_match",
                            "status_hint": "unknown",
                            "deadline_hint_source": "wp_content" if self._deadline_hint(post) else "none",
                            "requires_manual_review": self.requires_manual_review_by_default,
                            "manual_review_reason": self.manual_review_reason,
                            "raw_post": post,
                        },
                    )
                )

        if discovered or not self.source.feed_url:
            if not discovered and wp_rest_errors and not self.source.feed_url:
                raise ValueError(f"WordPress REST discovery failed: {wp_rest_errors[-1]}")
            return discovered
        return self._discover_rss(
            limit=limit,
            feed_url=self.source.feed_url,
            last_response_status=last_response_status,
            last_content_type=last_content_type,
            wp_rest_errors=wp_rest_errors,
        )

    def fetch_detail(self, item: DiscoveredGrantItemDraft) -> FetchedDetail:
        raw_post = item.discovery_metadata.get("raw_post")
        if isinstance(raw_post, dict):
            content_html = self._rendered_html(raw_post.get("content"))
            return FetchedDetail(
                source_url=item.source_url,
                raw_payload=raw_post,
                raw_html=content_html,
                raw_text=soup_text(content_html) if content_html else item.summary_hint,
                http_status=item.discovery_metadata.get("http_status"),
                content_type=item.discovery_metadata.get("content_type"),
                metadata={"source": self.source_slug, "detail_source": "wp_rest_content"},
            )

        detail = self.http.get(item.source_url)
        return FetchedDetail(
            source_url=item.source_url,
            raw_html=detail.text,
            raw_text=soup_text(detail.text),
            http_status=detail.status_code,
            content_type=detail.content_type,
            metadata={"source": self.source_slug, "detail_source": "html_detail"},
        )

    def normalize(self, item: DiscoveredGrantItemDraft, detail: FetchedDetail) -> NormalizedGrantDraft:
        html = detail.raw_html or ""
        text = detail.raw_text or soup_text(html) or item.summary_hint or item.title_hint or ""
        deadline_at, deadline_text = extract_deadline(text)
        title = self._title_from_detail_html(html) or item.title_hint or "Untitled grant opportunity"
        funding_amount_text = extract_funding_text(text)
        documents = extract_documents(item.source_url, html) if html else []
        return NormalizedGrantDraft(
            source_url=item.source_url,
            source_record_id=item.source_record_id,
            title=title,
            summary=item.summary_hint or self._summary(text),
            description_text=text or None,
            language=self.language,
            published_at=item.published_at_hint,
            deadline_at=deadline_at,
            deadline_text=deadline_text or item.deadline_hint,
            status=status_from_deadline(deadline_at),
            opportunity_type="grant",
            support_type="grant",
            funding_amount_text=funding_amount_text,
            documents=documents,
            source_metadata={
                "source": self.source_slug,
                "discovery_method": item.discovery_metadata.get("discovery_method"),
                "quality_level": item.discovery_metadata.get("quality_level"),
                "quality_reasons": item.discovery_metadata.get("quality_reasons", []),
            },
            extraction_method="deterministic",
            needs_manual_review=bool(item.discovery_metadata.get("requires_manual_review", False)),
            manual_review_reason=item.discovery_metadata.get("manual_review_reason"),
        )

    def _posts_api_url(self) -> str:
        if self.source.api_url:
            return self.source.api_url.rstrip("/")
        return f"{self.source.base_url.rstrip('/')}/wp-json/wp/v2/posts"

    def _search_terms(self) -> tuple[str, ...]:
        metadata_terms = self.source.source_metadata.get("wp_search_terms") if self.source.source_metadata else None
        if isinstance(metadata_terms, list):
            terms = tuple(clean_text(str(term)) for term in metadata_terms)
            return tuple(term for term in terms if term)
        return self.search_terms

    def _discover_rss(
        self,
        *,
        limit: int,
        feed_url: str,
        last_response_status: int | None,
        last_content_type: str | None,
        wp_rest_errors: list[str],
    ) -> list[DiscoveredGrantItemDraft]:
        response = self.http.get(feed_url)
        root = parse_xml(response.text)
        discovered: list[DiscoveredGrantItemDraft] = []
        for item in root.findall(".//item"):
            if len(discovered) >= limit:
                break
            parsed = self._parse_rss_item(item)
            if not parsed["link"] or not self._rss_item_is_grant_like(parsed):
                continue
            discovered.append(
                DiscoveredGrantItemDraft(
                    source_url=parsed["link"],
                    canonical_url=canonicalize_url(parsed["link"]),
                    source_record_id=parsed.get("guid") or parsed["link"],
                    title_hint=parsed.get("title"),
                    summary_hint=parsed.get("description"),
                    published_at_hint=parse_datetime(parsed.get("pub_date")),
                    listing_url=feed_url,
                    listing_position=len(discovered) + 1,
                    content_hash=content_hash(parsed),
                    discovery_metadata={
                        "discovery_method": "rss",
                        "feed_url": feed_url,
                        "wp_rest_http_status": last_response_status,
                        "wp_rest_content_type": last_content_type,
                        "wp_rest_errors": wp_rest_errors[:3],
                        "http_status": response.status_code,
                        "content_type": response.content_type,
                        "quality_level": self.default_quality_level,
                        "quality_reasons": [*self.default_quality_reasons, "rss_fallback"],
                        "is_probably_grant": True,
                        "is_probably_grant_reason": "rss_keyword_match",
                        "status_hint": "unknown",
                        "deadline_hint_source": "none",
                        "requires_manual_review": self.requires_manual_review_by_default,
                        "manual_review_reason": self.manual_review_reason,
                        "feed_item": parsed,
                    },
                )
            )
        return discovered

    @staticmethod
    def _json_list(response: Any) -> list[Any]:
        payload = response.json_data
        if payload is None:
            try:
                payload = json.loads(response.text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"WordPress REST did not return JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise ValueError("WordPress REST posts endpoint did not return a list")
        return payload

    @staticmethod
    def _rendered_html(value: object) -> str | None:
        if isinstance(value, dict):
            rendered = value.get("rendered")
            return str(rendered) if rendered is not None else None
        if isinstance(value, str):
            return value
        return None

    @classmethod
    def _rendered_text(cls, value: object) -> str | None:
        html = cls._rendered_html(value)
        if html is None:
            return clean_text(str(value)) if value is not None else None
        return clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))

    def _post_url(self, post: dict[str, Any]) -> str | None:
        link = clean_text(str(post.get("link") or ""))
        return absolute_url(self.source.base_url, link)

    def _is_grant_like(self, post: dict[str, Any]) -> bool:
        haystack = " ".join(
            text
            for text in (
                self._post_url(post),
                self._rendered_text(post.get("title")),
                self._rendered_text(post.get("excerpt")),
                self._rendered_text(post.get("content")),
            )
            if text
        ).lower()
        return any(keyword.lower() in haystack for keyword in self.grant_keywords)

    def _rss_item_is_grant_like(self, item: dict[str, str | None]) -> bool:
        haystack = " ".join(value for value in item.values() if value).lower()
        return any(keyword.lower() in haystack for keyword in self.grant_keywords)

    def _deadline_hint(self, post: dict[str, Any]) -> str | None:
        text = " ".join(
            text
            for text in (
                self._rendered_text(post.get("excerpt")),
                self._rendered_text(post.get("content")),
            )
            if text
        )
        _deadline_at, deadline_text = extract_deadline(text)
        return deadline_text

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

    @staticmethod
    def _title_from_detail_html(html: str) -> str | None:
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for selector in ("h1", "h2", "title"):
            node = soup.select_one(selector)
            text = clean_text(node.get_text(" ", strip=True) if node else None)
            if text:
                return text
        return None

    @staticmethod
    def _summary(text: str | None) -> str | None:
        cleaned = clean_text(text)
        if not cleaned:
            return None
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        return clean_text(" ".join(sentences[:2])) or cleaned[:280]


class ChasZminConnector(WordPressGrantConnector):
    source_slug = "chas-zmin"
    search_terms = ("грант", "конкурс", "можливості")
    language = "uk"
    default_quality_level = "high"


class EUFundingPortalEuConnector(WordPressGrantConnector):
    source_slug = "eufundingportal-eu"
    search_terms = ("grant", "funding", "programme")
    grant_keywords = WordPressGrantConnector.grant_keywords + ("programme", "european", "eu")
    language = "en"
    default_quality_level = "medium"
    default_quality_reasons = ("aggregator_or_broad_source", "duplicate_risk_with_official_eu_source")
    requires_manual_review_by_default = True
    manual_review_reason = "Aggregator source can duplicate official EU Funding opportunities."


class HromadyConnector(WordPressGrantConnector):
    source_slug = "hromady"
    search_terms = ("грант", "конкурс", "підтримка громад", "можливості")
    language = "uk"
    default_quality_level = "medium"
    default_quality_reasons = ("local_development_source",)
