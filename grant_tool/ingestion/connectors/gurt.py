from __future__ import annotations

from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.connectors.common import extract_filtered_links
from grant_tool.ingestion.types import ConnectorError, ConnectorResult, FetchedGrant, NormalizedGrantDraft
from grant_tool.ingestion.utils import (
    clean_text,
    extract_deadline,
    extract_documents,
    extract_funding_text,
    soup_text,
    status_from_deadline,
)


class GurtConnector(BaseConnector):
    source_slug = "gurt"

    def run(self, *, limit: int) -> ConnectorResult:
        if not self.source.list_url:
            return ConnectorResult(
                source_slug=self.source_slug,
                errors=[ConnectorError(message="Source list_url is not configured", stage="fetch_list")],
            )
        try:
            response = self.http.get(self.source.list_url)
        except Exception as exc:
            return ConnectorResult(
                source_slug=self.source_slug,
                errors=[ConnectorError(message=str(exc), source_url=self.source.list_url, stage="fetch_list")],
            )
        links = extract_filtered_links(
            base_url=self.source.base_url,
            html=response.text,
            include="/news/grants/",
            exclude_exact={self.source.list_url},
            limit=limit,
        )
        grants: list[FetchedGrant] = []
        errors: list[ConnectorError] = []
        for source_url, title_hint in links:
            try:
                detail = self.http.get(source_url)
                grants.append(
                    self._parse_detail(
                        source_url=source_url,
                        title_hint=title_hint,
                        detail_html=detail.text,
                        http_status=detail.status_code,
                        content_type=detail.content_type,
                    )
                )
            except Exception as exc:
                errors.append(ConnectorError(message=str(exc), source_url=source_url, stage="fetch_detail"))
        return ConnectorResult(source_slug=self.source_slug, grants=grants, errors=errors)

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
            language="uk",
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
