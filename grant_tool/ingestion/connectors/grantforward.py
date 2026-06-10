from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from grant_tool.ingestion.base import BaseConnector
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
    parse_datetime,
    soup_text,
    status_from_deadline,
)


class GrantForwardConnector(BaseConnector):
    source_slug = "grantforward"

    def discover(self, *, limit: int, mode: DiscoveryMode) -> list[DiscoveredGrantItemDraft]:
        if not self.source.api_url:
            raise ValueError("GrantForward api_url is not configured")
        list_url = self.source.list_url or f"{self.source.base_url.rstrip('/')}/search"
        self.http.get(list_url)

        response = self.http.post(
            self.source.api_url,
            data=self._search_payload(limit),
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": list_url,
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )
        payload = self._json_object(response)
        page_html = str(payload.get("page") or "")
        soup = BeautifulSoup(page_html, "html.parser")
        discovered: list[DiscoveredGrantItemDraft] = []
        for position, node in enumerate(soup.select(".result-item-wrapper[js-result-id]"), start=1):
            if len(discovered) >= limit:
                break
            parsed = self._parse_result_node(node, position)
            if not parsed:
                continue
            discovered.append(
                DiscoveredGrantItemDraft(
                    source_url=parsed["source_url"],
                    canonical_url=canonicalize_url(parsed["source_url"]),
                    source_record_id=parsed["grant_id"],
                    title_hint=parsed["title"],
                    summary_hint=parsed["summary"],
                    deadline_hint=parsed["deadline_text"],
                    listing_url=self.source.api_url,
                    listing_position=position,
                    content_hash=content_hash(parsed),
                    discovery_metadata={
                        "discovery_method": "grantforward_search_ajax",
                        "api_url": self.source.api_url,
                        "list_url": list_url,
                        "search_text": self._search_text(),
                        "http_status": response.status_code,
                        "content_type": response.content_type,
                        "quality_level": "medium",
                        "quality_reasons": ["public_search_result", "structured_deadline_and_amount"],
                        "is_probably_grant": True,
                        "is_probably_grant_reason": "grantforward_search_result",
                        "status_hint": "unknown",
                        "deadline_hint_source": "search_result_html" if parsed["deadline_text"] else "none",
                        "requires_manual_review": True,
                        "manual_review_reason": (
                            "GrantForward detail pages require login; normalized data is limited to public search fields."
                        ),
                        "detail_requires_login": True,
                        "raw_result_html": str(node),
                        "sponsors": parsed["sponsors"],
                        "amount_text": parsed["amount_text"],
                        "result_payload": {
                            "hits": payload.get("hits"),
                            "total_count": payload.get("total_count"),
                            "grant_ids": payload.get("grant_ids"),
                        },
                    },
                )
            )
        return discovered

    def fetch_detail(self, item: DiscoveredGrantItemDraft) -> FetchedDetail:
        raw_html = str(item.discovery_metadata.get("raw_result_html") or "")
        return FetchedDetail(
            source_url=item.source_url,
            raw_payload={
                "grant_id": item.source_record_id,
                "title": item.title_hint,
                "summary": item.summary_hint,
                "deadline_text": item.deadline_hint,
                "amount_text": item.discovery_metadata.get("amount_text"),
                "sponsors": item.discovery_metadata.get("sponsors", []),
            },
            raw_html=raw_html,
            raw_text=soup_text(raw_html) if raw_html else item.summary_hint,
            http_status=item.discovery_metadata.get("http_status"),
            content_type=item.discovery_metadata.get("content_type"),
            metadata={"source": self.source_slug, "detail_source": "public_search_result"},
        )

    def normalize(self, item: DiscoveredGrantItemDraft, detail: FetchedDetail) -> NormalizedGrantDraft:
        sponsors = item.discovery_metadata.get("sponsors", [])
        if not isinstance(sponsors, list):
            sponsors = []
        deadline_at = parse_datetime(item.deadline_hint)
        amount_text = clean_text(str(item.discovery_metadata.get("amount_text") or ""))
        text_parts = [
            item.title_hint,
            item.summary_hint,
            f"Deadline: {item.deadline_hint}" if item.deadline_hint else None,
            f"Amount: {amount_text}" if amount_text else None,
            f"Sponsors: {', '.join(str(sponsor) for sponsor in sponsors)}" if sponsors else None,
        ]
        description_text = clean_text(" ".join(part for part in text_parts if part))
        return NormalizedGrantDraft(
            source_url=item.source_url,
            source_record_id=item.source_record_id,
            title=item.title_hint or "Untitled GrantForward opportunity",
            summary=item.summary_hint,
            description_text=description_text,
            deadline_at=deadline_at,
            deadline_text=item.deadline_hint,
            status=status_from_deadline(deadline_at),
            opportunity_type="grant",
            support_type="grant",
            funder_name=clean_text(str(sponsors[0])) if sponsors else None,
            funding_amount_text=amount_text or None,
            source_metadata={
                "source": self.source_slug,
                "discovery_method": item.discovery_metadata.get("discovery_method"),
                "quality_level": item.discovery_metadata.get("quality_level"),
                "quality_reasons": item.discovery_metadata.get("quality_reasons", []),
                "detail_requires_login": True,
                "sponsors": sponsors,
            },
            needs_manual_review=True,
            manual_review_reason=item.discovery_metadata.get("manual_review_reason"),
        )

    def _search_payload(self, limit: int) -> dict[str, Any]:
        query = [[{"field": "search_text", "operator": "=", "value": self._search_text()}]]
        return {
            "query": json.dumps(query),
            "limit": min(max(limit, 1), 10),
            "offset": 0,
            "sort_direction": "desc",
            "view_mode": "origin",
            "view_options[]": ["grant_list", "amount", "deadline", "grant_action"],
        }

    def _search_text(self) -> str:
        value = self.source.source_metadata.get("grantforward_search_text") if self.source.source_metadata else None
        return clean_text(str(value)) if value else "ukraine"

    @staticmethod
    def _json_object(response: Any) -> dict[str, Any]:
        payload = response.json_data
        if payload is None:
            try:
                payload = json.loads(response.text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"GrantForward search did not return JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("GrantForward search endpoint did not return an object")
        return payload

    def _parse_result_node(self, node: Any, position: int) -> dict[str, Any] | None:
        grant_id = clean_text(str(node.get("js-result-id") or ""))
        link = node.select_one(".grant-url[href]")
        href = link.get("href") if link else None
        source_url = absolute_url(self.source.base_url, href)
        if not grant_id or not source_url:
            return None
        title = self._clean_title(link.get_text(" ", strip=True) if link else None)
        summary = clean_text(self._selector_text(node, ".description"))
        sponsors = self._sponsors(node)
        deadline_text = self._deadline_text(node)
        amount_text = self._amount_text(node)
        return {
            "grant_id": grant_id,
            "source_url": source_url,
            "title": title or f"GrantForward opportunity {grant_id}",
            "summary": summary,
            "deadline_text": deadline_text,
            "amount_text": amount_text,
            "sponsors": sponsors,
            "position": position,
        }

    @staticmethod
    def _selector_text(node: Any, selector: str) -> str | None:
        selected = node.select_one(selector)
        return clean_text(selected.get_text(" ", strip=True) if selected else None)

    @staticmethod
    def _clean_title(title: str | None) -> str | None:
        cleaned = clean_text(title)
        if not cleaned:
            return None
        return re.sub(r"\s+", " ", cleaned.replace("Grant Title:", "")).strip()

    @staticmethod
    def _sponsors(node: Any) -> list[str]:
        sponsors: list[str] = []
        for link in node.select(".sponsor a[href]"):
            href = str(link.get("href") or "")
            if not href.startswith("/sponsor/detail/"):
                continue
            sponsor = clean_text(link.get_text(" ", strip=True))
            if sponsor and sponsor not in sponsors:
                sponsors.append(sponsor)
        return sponsors

    @staticmethod
    def _deadline_text(node: Any) -> str | None:
        table_dates = [
            clean_text(cell.get_text(" ", strip=True))
            for cell in node.select(".deadline-tables tbody tr:not(.deadline-passed) td:first-child")
        ]
        for value in table_dates:
            if value:
                return value
        return clean_text(GrantForwardConnector._selector_text(node, ".deadline-value"))

    @staticmethod
    def _amount_text(node: Any) -> str | None:
        amount = node.select_one(".amount")
        if not amount:
            return None
        aria = clean_text(str(amount.get("aria-label") or ""))
        if aria:
            cleaned = re.sub(r"(?i)^funding amount:\s*", "", aria).strip()
            return clean_text(cleaned)
        text = clean_text(amount.get_text(" ", strip=True))
        return text
