from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.connectors.common import extract_filtered_links, parse_sitemap_urls
from grant_tool.ingestion.types import ConnectorError, ConnectorResult, FetchedGrant, NormalizedGrantDraft
from grant_tool.ingestion.utils import (
    clean_text,
    extract_deadline,
    extract_documents,
    extract_funding_text,
    soup_text,
    status_from_deadline,
)


class DiiaBusinessConnector(BaseConnector):
    source_slug = "diia-business"
    default_api_url = "https://api.business.diia.gov.ua/api/front"

    def run(self, *, limit: int) -> ConnectorResult:
        errors: list[ConnectorError] = []
        grants = self._run_api(limit=limit, errors=errors)
        if grants:
            return ConnectorResult(source_slug=self.source_slug, grants=grants, errors=errors)

        detail_urls: list[tuple[str, str | None]] = []
        if self.source.sitemap_url:
            try:
                sitemap = self.http.get(self.source.sitemap_url)
                urls = self._finance_urls_from_sitemap(sitemap.text, limit=limit)
                detail_urls.extend((url, None) for url in urls)
            except Exception as exc:
                errors.append(ConnectorError(message=str(exc), stage="fetch_sitemap", source_url=self.source.sitemap_url))

        if not detail_urls and self.source.list_url:
            try:
                listing = self.http.get(self.source.list_url)
                detail_urls.extend(
                    extract_filtered_links(
                        base_url=self.source.base_url,
                        html=listing.text,
                        include="/finance/",
                        exclude_exact={self.source.list_url},
                        limit=limit,
                    )
                )
            except Exception as exc:
                errors.append(ConnectorError(message=str(exc), stage="fetch_list", source_url=self.source.list_url))

        grants: list[FetchedGrant] = []
        for url, title_hint in detail_urls[:limit]:
            try:
                detail = self.http.get(url)
                grants.append(
                    self._parse_detail(
                        source_url=url,
                        title_hint=title_hint,
                        detail_html=detail.text,
                        http_status=detail.status_code,
                        content_type=detail.content_type,
                    )
                )
            except Exception as exc:
                errors.append(ConnectorError(message=str(exc), source_url=url, stage="fetch_detail"))
        return ConnectorResult(source_slug=self.source_slug, grants=grants, errors=errors)

    def _run_api(self, *, limit: int, errors: list[ConnectorError]) -> list[FetchedGrant]:
        api_url = (self.source.api_url or self.default_api_url).rstrip("/")
        list_url = f"{api_url}/finance"
        try:
            response = self.http.get(list_url, params={"take": limit, "skip": 0, "date": self._cache_uid()})
        except Exception as exc:
            errors.append(ConnectorError(message=str(exc), stage="fetch_api_list", source_url=list_url))
            return []

        payload = self._json(response)
        if not isinstance(payload, dict):
            errors.append(ConnectorError(message="Diia finance API returned a non-object payload", stage="parse_api_list", source_url=list_url))
            return []

        rows = payload.get("data")
        if not isinstance(rows, list):
            errors.append(ConnectorError(message="Diia finance API response does not contain data[]", stage="parse_api_list", source_url=list_url))
            return []

        grants: list[FetchedGrant] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug") or "").strip()
            if not slug:
                continue
            detail_payload: dict[str, Any] = {"service": row, "similar": []}
            detail_status = response.status_code
            detail_content_type = response.content_type
            detail_url = f"{api_url}/finance/service/{slug}"
            try:
                detail = self.http.get(detail_url, params={"date": self._cache_uid()})
                detail_status = detail.status_code
                detail_content_type = detail.content_type
                candidate = self._json(detail)
                if isinstance(candidate, dict) and isinstance(candidate.get("service"), dict):
                    detail_payload = candidate
            except Exception as exc:
                errors.append(ConnectorError(message=str(exc), source_url=detail_url, stage="fetch_api_detail"))
            grants.append(
                self._parse_api_service(
                    payload=detail_payload,
                    http_status=detail_status,
                    content_type=detail_content_type,
                )
            )
        return grants

    def _parse_api_service(
        self,
        *,
        payload: dict[str, Any],
        http_status: int,
        content_type: str | None,
    ) -> FetchedGrant:
        service = payload.get("service") if isinstance(payload.get("service"), dict) else payload
        assert isinstance(service, dict)

        slug = str(service.get("slug") or service.get("id") or "").strip()
        title = clean_text(str(service.get("title") or "")) or "Untitled Diia Business finance service"
        description = clean_text(str(service.get("description") or "")) or None
        source_url = self._web_finance_url(slug)
        attributes = self._attributes(service)
        attribute_lines = [f"{label}: {value}" for label, value in attributes if value]
        text = clean_text("\n".join([title, description or "", str(service.get("companyName") or ""), *attribute_lines]))

        deadline_text = self._attribute_value(attributes, "finalProgramTerm", "Кінцевий строк дії програми")
        deadline_at, parsed_deadline_text = extract_deadline(deadline_text or text)
        if deadline_text and not parsed_deadline_text:
            parsed_deadline_text = deadline_text

        funding_amount_text = self._attribute_value(attributes, "grantAmount", "Сума")
        currency = self._normalise_currency(self._attribute_value(attributes, "currency", "Валюта"))
        geography_text = self._attribute_value(attributes, "Область", "Регіон", "Географія")
        category = service.get("category") if isinstance(service.get("category"), dict) else {}
        category_title = self._translation_title(category)
        company_name = clean_text(str(service.get("companyName") or "")) or None
        status = self._status_from_program_term(deadline_text, deadline_at)

        support_type = self._support_type(title=title, category_title=category_title, attributes=attributes)
        opportunity_type = "grant" if support_type == "grant" else "business_support"
        normalized = NormalizedGrantDraft(
            source_url=source_url,
            source_record_id=str(service.get("id") or slug),
            application_url=clean_text(str(service.get("externalLink") or "")) or source_url,
            title=title,
            summary=description or self._summary(text),
            description_text=text,
            language="uk",
            deadline_at=deadline_at,
            deadline_text=parsed_deadline_text,
            status=status,
            program_name=category_title,
            funder_name=company_name,
            opportunity_type=opportunity_type,
            support_type=support_type,
            funding_amount_text=funding_amount_text,
            currency=currency,
            geography_text=geography_text,
            countries=["Ukraine"],
            regions=[geography_text] if geography_text else [],
            eligibility_text=self._attribute_value(attributes, "umoviuchasti", "Умови участі"),
            topics=[category_title] if category_title else [],
            implementation_period_text=deadline_text,
            source_metadata={
                "detail_url": source_url,
                "api_kind": "diia_business_finance_service",
                "api_service_id": service.get("id"),
                "category_slug": category.get("slug") if isinstance(category, dict) else None,
                "category_title": category_title,
                "attributes": [{"key": key, "value": value} for key, value in attributes],
            },
            extraction_metadata={"connector": self.source_slug, "api_url": self.source.api_url or self.default_api_url},
        )
        return FetchedGrant(
            normalized=normalized,
            raw_payload=payload,
            raw_text=text,
            raw_title=title,
            raw_summary=normalized.summary,
            http_status=http_status,
            content_type=content_type,
            snapshot_metadata={"source": self.source_slug, "detail_url": source_url, "api_service_id": service.get("id")},
        )

    def _parse_detail(
        self,
        *,
        source_url: str,
        title_hint: str | None,
        detail_html: str,
        http_status: int,
        content_type: str | None,
    ) -> FetchedGrant:
        text = soup_text(detail_html)
        title = self._extract_title(detail_html) or title_hint or "Untitled Diia Business programme"
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
            opportunity_type="business_support",
            support_type="finance_programme",
            funding_amount_text=extract_funding_text(text),
            documents=extract_documents(self.source.base_url, detail_html),
            source_metadata={"detail_url": source_url, "source_kind": "diia_business_finance_programme"},
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
        for selector in ("h1", "title", "h2"):
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

    @staticmethod
    def _cache_uid() -> str:
        return str(int(datetime.now(tz=UTC).timestamp() * 1000))

    @staticmethod
    def _json(response: Any) -> Any:
        if response.json_data is not None:
            return response.json_data
        import json

        return json.loads(response.text)

    def _web_finance_url(self, slug: str) -> str:
        return f"{self.source.base_url.rstrip('/')}/finance/{slug}"

    @staticmethod
    def _finance_urls_from_sitemap(sitemap_text: str, *, limit: int) -> list[str]:
        urls = parse_sitemap_urls(sitemap_text, contains="/finance/", limit=limit * 4)
        filtered: list[str] = []
        for url in urls:
            path = urlparse(url).path
            if path in {"/finance", "/finance/programs"}:
                continue
            if path.startswith("/finance/programs/") or path.startswith("/finance/handbook/"):
                continue
            filtered.append(url)
            if len(filtered) >= limit:
                break
        return filtered

    @staticmethod
    def _attributes(service: dict[str, Any]) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for item in service.get("serviceAttributes") or []:
            if not isinstance(item, dict):
                continue
            value = clean_text(str(item.get("value") or ""))
            category_attribute = item.get("categoryAttribute") if isinstance(item.get("categoryAttribute"), dict) else {}
            attribute = category_attribute.get("attribute") if isinstance(category_attribute.get("attribute"), dict) else {}
            name = clean_text(str(attribute.get("name") or ""))
            title = DiiaBusinessConnector._translation_title(attribute)
            label = name or title
            if label and value:
                rows.append((label, value))
        return rows

    @staticmethod
    def _translation_title(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        translations = payload.get("translations")
        if isinstance(translations, list):
            for preferred_locale in ("ua", "uk", "en"):
                for translation in translations:
                    if isinstance(translation, dict) and translation.get("locale") == preferred_locale:
                        title = clean_text(str(translation.get("title") or ""))
                        if title:
                            return title
            for translation in translations:
                if isinstance(translation, dict):
                    title = clean_text(str(translation.get("title") or ""))
                    if title:
                        return title
        return clean_text(str(payload.get("title") or "")) or None

    @staticmethod
    def _attribute_value(attributes: list[tuple[str, str]], *keys: str) -> str | None:
        normalised_keys = {DiiaBusinessConnector._normalise_key(key) for key in keys}
        for key, value in attributes:
            if DiiaBusinessConnector._normalise_key(key) in normalised_keys:
                return value
        return None

    @staticmethod
    def _normalise_key(value: str) -> str:
        return re.sub(r"[^a-zа-яіїєґ0-9]+", "", value.lower())

    @staticmethod
    def _normalise_currency(value: str | None) -> str | None:
        if not value:
            return None
        upper = value.strip().upper()
        aliases = {
            "ГРН": "UAH",
            "UAH": "UAH",
            "USD": "USD",
            "ДОЛАР": "USD",
            "ДОЛАРИ": "USD",
            "EUR": "EUR",
            "ЄВРО": "EUR",
        }
        for token, code in aliases.items():
            if token in upper:
                return code
        return clean_text(value)

    @staticmethod
    def _status_from_program_term(deadline_text: str | None, deadline_at: Any) -> str:
        if deadline_text:
            lower = deadline_text.lower()
            if "постій" in lower or "безстрок" in lower:
                return "open"
            years = [int(year) for year in re.findall(r"\b20\d{2}\b", deadline_text)]
            if years:
                return "open" if max(years) >= datetime.now(tz=UTC).year else "closed"
        return status_from_deadline(deadline_at)

    @staticmethod
    def _support_type(*, title: str, category_title: str | None, attributes: list[tuple[str, str]]) -> str:
        haystack = " ".join([title, category_title or "", *[value for _, value in attributes]]).lower()
        if "грант" in haystack:
            return "grant"
        if "кредит" in haystack:
            return "loan"
        if "гарант" in haystack:
            return "guarantee"
        if "лізинг" in haystack or "leasing" in haystack:
            return "leasing"
        if "факторинг" in haystack:
            return "factoring"
        if "тендер" in haystack:
            return "tender_support"
        return "finance_programme"
