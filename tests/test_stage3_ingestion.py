from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, DiscoveredGrantItem, Grant, JobStatus, RawGrantSnapshot, Source
from grant_tool.db.repositories import GrantRepository
from grant_tool.ingestion.connectors import (
    ChasZminConnector,
    CONNECTOR_CLASSES,
    DiiaBusinessConnector,
    EUFundingPortalEuConnector,
    EUFundingConnector,
    FundsForNgosConnector,
    GrantMarketConnector,
    GurtConnector,
    HromadyConnector,
    NipoConnector,
    OpportunityDeskConnector,
    ProstirConnector,
)
from grant_tool.ingestion.http import HttpResponse
from grant_tool.ingestion.service import IngestionService
from grant_tool.ingestion.types import DetailFetchStatus


FIXTURES = Path(__file__).parent / "fixtures"


class FakeHttpClient:
    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> HttpResponse:
        self.calls.append(("GET", url))
        if url not in self.responses:
            raise AssertionError(f"Unexpected GET URL: {url}")
        return self.responses[url]

    def post(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any | None = None,
        files: Any | None = None,
        json: Any | None = None,
    ) -> HttpResponse:
        self.calls.append(("POST", url))
        if url not in self.responses:
            raise AssertionError(f"Unexpected POST URL: {url}")
        return self.responses[url]

    def close(self) -> None:
        pass

    def count_calls(self, method: str, url: str) -> int:
        return self.calls.count((method, url))


def text_fixture(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


def json_response(url: str, path: str) -> HttpResponse:
    text = text_fixture(path)
    return HttpResponse(
        url=url,
        status_code=200,
        content_type="application/json",
        text=text,
        json_data=json.loads(text),
    )


def html_response(url: str, path: str, content_type: str = "text/html") -> HttpResponse:
    return HttpResponse(
        url=url,
        status_code=200,
        content_type=content_type,
        text=text_fixture(path),
    )


def source_fixture_cases() -> list[dict[str, Any]]:
    eu_api_url = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
    prostir_feed_url = "https://www.prostir.ua/category/grants/feed/"
    prostir_detail_url = "https://www.prostir.ua/grant/test-grant/"
    diia_api_url = "https://api.business.diia.gov.ua/api/front"
    diia_list_url = f"{diia_api_url}/finance"
    diia_detail_url = f"{diia_api_url}/finance/service/grant_na_vlasnu_spravu"
    gurt_list_url = "https://gurt.org.ua/news/grants/"
    gurt_detail_url = "https://gurt.org.ua/news/grants/test-grant/"
    chas_api_url = "https://chaszmin.com.ua/wp-json/wp/v2/posts"
    eufundingportal_api_url = "https://eufundingportal.eu/wp-json/wp/v2/posts"
    hromady_api_url = "https://hromady.org/wp-json/wp/v2/posts"
    nipo_api_url = "https://nipo.gov.ua/wp-json/wp/v2/posts"
    grant_market_sitemap_url = "https://grant.market/sitemap.xml"
    grant_market_detail_url = "https://grant.market/opp/ebrd-consulting"
    fundsforngos_api_url = "https://www2.fundsforngos.org/wp-json/wp/v2/posts"
    opportunitydesk_api_url = "https://www.opportunitydesk.org/wp-json/wp/v2/posts"
    return [
        {
            "slug": "eu-funding",
            "access_strategy": AccessStrategy.API,
            "base_url": "https://ec.europa.eu",
            "api_url": eu_api_url,
            "responses": {eu_api_url: json_response(eu_api_url, "eu_funding/search_response.json")},
            "listing_url": eu_api_url,
            "listing_method": "POST",
            "detail_urls": [],
        },
        {
            "slug": "prostir",
            "access_strategy": AccessStrategy.RSS,
            "base_url": "https://www.prostir.ua",
            "feed_url": prostir_feed_url,
            "responses": {
                prostir_feed_url: html_response(prostir_feed_url, "prostir/feed.xml", "application/rss+xml"),
                prostir_detail_url: html_response(prostir_detail_url, "prostir/detail.html"),
            },
            "listing_url": prostir_feed_url,
            "listing_method": "GET",
            "detail_urls": [prostir_detail_url],
        },
        {
            "slug": "diia-business",
            "access_strategy": AccessStrategy.API,
            "base_url": "https://www.business.diia.gov.ua",
            "api_url": diia_api_url,
            "responses": {
                diia_list_url: json_response(diia_list_url, "diia_business/finance_list.json"),
                diia_detail_url: json_response(diia_detail_url, "diia_business/finance_detail.json"),
            },
            "listing_url": diia_list_url,
            "listing_method": "GET",
            "detail_urls": [diia_detail_url],
        },
        {
            "slug": "gurt",
            "access_strategy": AccessStrategy.HTML,
            "base_url": "https://gurt.org.ua",
            "list_url": gurt_list_url,
            "responses": {
                gurt_list_url: html_response(gurt_list_url, "gurt/list.html"),
                gurt_detail_url: html_response(gurt_detail_url, "gurt/detail.html"),
            },
            "listing_url": gurt_list_url,
            "listing_method": "GET",
            "detail_urls": [gurt_detail_url],
        },
        {
            "slug": "chas-zmin",
            "access_strategy": AccessStrategy.WP_REST,
            "base_url": "https://chaszmin.com.ua",
            "api_url": chas_api_url,
            "feed_url": "https://chaszmin.com.ua/feed/",
            "responses": {chas_api_url: json_response(chas_api_url, "chas_zmin/posts.json")},
            "listing_url": chas_api_url,
            "listing_method": "GET",
            "detail_urls": [],
        },
        {
            "slug": "eufundingportal-eu",
            "access_strategy": AccessStrategy.WP_REST,
            "base_url": "https://eufundingportal.eu",
            "api_url": eufundingportal_api_url,
            "feed_url": "https://eufundingportal.eu/feed/",
            "responses": {
                eufundingportal_api_url: json_response(eufundingportal_api_url, "eufundingportal_eu/posts.json")
            },
            "listing_url": eufundingportal_api_url,
            "listing_method": "GET",
            "detail_urls": [],
        },
        {
            "slug": "hromady",
            "access_strategy": AccessStrategy.WP_REST,
            "base_url": "https://hromady.org",
            "api_url": hromady_api_url,
            "feed_url": "https://hromady.org/feed/",
            "responses": {hromady_api_url: json_response(hromady_api_url, "hromady/posts.json")},
            "listing_url": hromady_api_url,
            "listing_method": "GET",
            "detail_urls": [],
        },
        {
            "slug": "nipo",
            "access_strategy": AccessStrategy.WP_REST,
            "base_url": "https://nipo.gov.ua",
            "api_url": nipo_api_url,
            "feed_url": "https://nipo.gov.ua/feed/",
            "responses": {nipo_api_url: json_response(nipo_api_url, "nipo/posts.json")},
            "listing_url": nipo_api_url,
            "listing_method": "GET",
            "detail_urls": [],
        },
        {
            "slug": "grant-market",
            "access_strategy": AccessStrategy.SITEMAP_HTML,
            "base_url": "https://grant.market",
            "sitemap_url": grant_market_sitemap_url,
            "responses": {
                grant_market_sitemap_url: html_response(
                    grant_market_sitemap_url,
                    "grant_market/sitemap.xml",
                    "application/xml",
                ),
                grant_market_detail_url: html_response(grant_market_detail_url, "grant_market/detail.html"),
            },
            "listing_url": grant_market_sitemap_url,
            "listing_method": "GET",
            "detail_urls": [grant_market_detail_url],
        },
        {
            "slug": "fundsforngos",
            "access_strategy": AccessStrategy.WP_REST,
            "base_url": "https://www2.fundsforngos.org",
            "api_url": fundsforngos_api_url,
            "feed_url": "https://www2.fundsforngos.org/feed/",
            "responses": {fundsforngos_api_url: json_response(fundsforngos_api_url, "fundsforngos/posts.json")},
            "listing_url": fundsforngos_api_url,
            "listing_method": "GET",
            "detail_urls": [],
        },
        {
            "slug": "opportunitydesk",
            "access_strategy": AccessStrategy.WP_REST,
            "base_url": "https://www.opportunitydesk.org",
            "api_url": opportunitydesk_api_url,
            "feed_url": "https://www.opportunitydesk.org/feed/",
            "responses": {opportunitydesk_api_url: json_response(opportunitydesk_api_url, "opportunitydesk/posts.json")},
            "listing_url": opportunitydesk_api_url,
            "listing_method": "GET",
            "detail_urls": [],
        },
    ]


class Stage3IngestionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.session: Session = self.session_factory()
        self.repository = GrantRepository(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def source(
        self,
        *,
        slug: str,
        access_strategy: AccessStrategy,
        base_url: str,
        list_url: str | None = None,
        api_url: str | None = None,
        feed_url: str | None = None,
        sitemap_url: str | None = None,
    ) -> Source:
        return self.repository.upsert_source(
            slug=slug,
            name=slug,
            base_url=base_url,
            access_strategy=access_strategy,
            list_url=list_url,
            api_url=api_url,
            feed_url=feed_url,
            sitemap_url=sitemap_url,
            rate_limit_seconds=0,
        )

    def test_eu_funding_connector_parses_api_results(self) -> None:
        api_url = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
        source = self.source(
            slug="eu-funding",
            access_strategy=AccessStrategy.API,
            base_url="https://ec.europa.eu",
            api_url=api_url,
        )
        connector = EUFundingConnector(
            source=source,
            http_client=FakeHttpClient({api_url: json_response(api_url, "eu_funding/search_response.json")}),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.source_record_id, "HORIZON-TEST-01")
        self.assertIn("AI", grant.keywords)
        self.assertEqual(grant.funder_name, "European Commission")

    def test_prostir_connector_parses_feed_and_detail(self) -> None:
        feed_url = "https://www.prostir.ua/category/grants/feed/"
        detail_url = "https://www.prostir.ua/grant/test-grant/"
        source = self.source(
            slug="prostir",
            access_strategy=AccessStrategy.RSS,
            base_url="https://www.prostir.ua",
            feed_url=feed_url,
        )
        connector = ProstirConnector(
            source=source,
            http_client=FakeHttpClient(
                {
                    feed_url: html_response(feed_url, "prostir/feed.xml", "application/rss+xml"),
                    detail_url: html_response(detail_url, "prostir/detail.html"),
                }
            ),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.status, "open")
        self.assertEqual(grant.language, "uk")
        self.assertTrue(grant.documents)

    def test_diia_business_connector_parses_api_finance_service(self) -> None:
        api_url = "https://api.business.diia.gov.ua/api/front"
        list_url = f"{api_url}/finance"
        detail_url = f"{api_url}/finance/service/grant_na_vlasnu_spravu"
        source = self.source(
            slug="diia-business",
            access_strategy=AccessStrategy.API,
            base_url="https://www.business.diia.gov.ua",
            api_url=api_url,
        )
        connector = DiiaBusinessConnector(
            source=source,
            http_client=FakeHttpClient(
                {
                    list_url: json_response(list_url, "diia_business/finance_list.json"),
                    detail_url: json_response(detail_url, "diia_business/finance_detail.json"),
                }
            ),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.source_url, "https://www.business.diia.gov.ua/finance/grant_na_vlasnu_spravu")
        self.assertEqual(grant.opportunity_type, "grant")
        self.assertEqual(grant.support_type, "grant")
        self.assertEqual(grant.funding_amount_text, "До 250 000")
        self.assertEqual(grant.currency, "UAH")
        self.assertEqual(grant.funder_name, "Урядовий проєкт єРобота")
        self.assertEqual(grant.geography_text, "Вся Україна")
        self.assertEqual(grant.status, "open")

    def test_gurt_connector_parses_list_and_detail(self) -> None:
        list_url = "https://gurt.org.ua/news/grants/"
        detail_url = "https://gurt.org.ua/news/grants/test-grant/"
        source = self.source(
            slug="gurt",
            access_strategy=AccessStrategy.HTML,
            base_url="https://gurt.org.ua",
            list_url=list_url,
        )
        connector = GurtConnector(
            source=source,
            http_client=FakeHttpClient(
                {
                    list_url: html_response(list_url, "gurt/list.html"),
                    detail_url: html_response(detail_url, "gurt/detail.html"),
                }
            ),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.status, "open")
        self.assertEqual(grant.opportunity_type, "grant")

    def test_gurt_connector_returns_error_when_list_fetch_fails(self) -> None:
        list_url = "https://gurt.org.ua/news/grants/"
        source = self.source(
            slug="gurt",
            access_strategy=AccessStrategy.HTML,
            base_url="https://gurt.org.ua",
            list_url=list_url,
        )
        connector = GurtConnector(source=source, http_client=FakeHttpClient({}))

        result = connector.run(limit=20)

        self.assertEqual(len(result.grants), 0)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].stage, "discover")
        self.assertEqual(result.errors[0].source_url, list_url)

    def test_chas_zmin_connector_parses_wp_rest_posts(self) -> None:
        api_url = "https://chaszmin.com.ua/wp-json/wp/v2/posts"
        source = self.source(
            slug="chas-zmin",
            access_strategy=AccessStrategy.WP_REST,
            base_url="https://chaszmin.com.ua",
            api_url=api_url,
            feed_url="https://chaszmin.com.ua/feed/",
        )
        connector = ChasZminConnector(
            source=source,
            http_client=FakeHttpClient({api_url: json_response(api_url, "chas_zmin/posts.json")}),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.source_record_id, "101")
        self.assertEqual(grant.status, "open")
        self.assertEqual(grant.language, "uk")
        self.assertEqual(grant.funding_amount_text, "300 000 грн")
        self.assertTrue(grant.documents)

    def test_eufundingportal_eu_connector_marks_aggregator_review(self) -> None:
        api_url = "https://eufundingportal.eu/wp-json/wp/v2/posts"
        source = self.source(
            slug="eufundingportal-eu",
            access_strategy=AccessStrategy.WP_REST,
            base_url="https://eufundingportal.eu",
            api_url=api_url,
            feed_url="https://eufundingportal.eu/feed/",
        )
        connector = EUFundingPortalEuConnector(
            source=source,
            http_client=FakeHttpClient({api_url: json_response(api_url, "eufundingportal_eu/posts.json")}),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.source_record_id, "202")
        self.assertEqual(grant.status, "open")
        self.assertEqual(grant.language, "en")
        self.assertTrue(grant.needs_manual_review)
        self.assertIn("official EU Funding", grant.manual_review_reason)

    def test_hromady_connector_parses_wp_rest_posts(self) -> None:
        api_url = "https://hromady.org/wp-json/wp/v2/posts"
        source = self.source(
            slug="hromady",
            access_strategy=AccessStrategy.WP_REST,
            base_url="https://hromady.org",
            api_url=api_url,
            feed_url="https://hromady.org/feed/",
        )
        connector = HromadyConnector(
            source=source,
            http_client=FakeHttpClient({api_url: json_response(api_url, "hromady/posts.json")}),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.source_record_id, "303")
        self.assertEqual(grant.status, "open")
        self.assertEqual(grant.language, "uk")
        self.assertEqual(grant.opportunity_type, "grant")

    def test_nipo_connector_marks_digest_review(self) -> None:
        api_url = "https://nipo.gov.ua/wp-json/wp/v2/posts"
        source = self.source(
            slug="nipo",
            access_strategy=AccessStrategy.WP_REST,
            base_url="https://nipo.gov.ua",
            api_url=api_url,
            feed_url="https://nipo.gov.ua/feed/",
        )
        connector = NipoConnector(
            source=source,
            http_client=FakeHttpClient({api_url: json_response(api_url, "nipo/posts.json")}),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.source_record_id, "404")
        self.assertEqual(grant.status, "open")
        self.assertEqual(grant.language, "uk")
        self.assertEqual(grant.funding_amount_text, "500 000 грн")
        self.assertTrue(grant.documents)
        self.assertTrue(grant.needs_manual_review)
        self.assertIn("digest/news", grant.manual_review_reason)

    def test_grant_market_connector_parses_sitemap_and_detail(self) -> None:
        sitemap_url = "https://grant.market/sitemap.xml"
        detail_url = "https://grant.market/opp/ebrd-consulting"
        source = self.source(
            slug="grant-market",
            access_strategy=AccessStrategy.SITEMAP_HTML,
            base_url="https://grant.market",
            sitemap_url=sitemap_url,
        )
        connector = GrantMarketConnector(
            source=source,
            http_client=FakeHttpClient(
                {
                    sitemap_url: html_response(sitemap_url, "grant_market/sitemap.xml", "application/xml"),
                    detail_url: html_response(detail_url, "grant_market/detail.html"),
                }
            ),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.source_record_id, detail_url)
        self.assertEqual(grant.title, "Грант на консалтингові послуги")
        self.assertEqual(grant.status, "open")
        self.assertEqual(grant.language, "uk")
        self.assertTrue(grant.documents)

    def test_fundsforngos_connector_marks_broad_source_review(self) -> None:
        api_url = "https://www2.fundsforngos.org/wp-json/wp/v2/posts"
        source = self.source(
            slug="fundsforngos",
            access_strategy=AccessStrategy.WP_REST,
            base_url="https://www2.fundsforngos.org",
            api_url=api_url,
            feed_url="https://www2.fundsforngos.org/feed/",
        )
        connector = FundsForNgosConnector(
            source=source,
            http_client=FakeHttpClient({api_url: json_response(api_url, "fundsforngos/posts.json")}),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.source_record_id, "505")
        self.assertEqual(grant.status, "open")
        self.assertEqual(grant.language, "en")
        self.assertIn("USD 25,000", grant.funding_amount_text or "")
        self.assertTrue(grant.needs_manual_review)
        self.assertIn("Broad international", grant.manual_review_reason)

    def test_opportunitydesk_connector_marks_broad_source_review(self) -> None:
        api_url = "https://www.opportunitydesk.org/wp-json/wp/v2/posts"
        source = self.source(
            slug="opportunitydesk",
            access_strategy=AccessStrategy.WP_REST,
            base_url="https://www.opportunitydesk.org",
            api_url=api_url,
            feed_url="https://www.opportunitydesk.org/feed/",
        )
        connector = OpportunityDeskConnector(
            source=source,
            http_client=FakeHttpClient({api_url: json_response(api_url, "opportunitydesk/posts.json")}),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.source_record_id, "606")
        self.assertEqual(grant.status, "open")
        self.assertEqual(grant.language, "en")
        self.assertIn("EUR 50,000", grant.funding_amount_text or "")
        self.assertTrue(grant.documents)
        self.assertTrue(grant.needs_manual_review)
        self.assertIn("Broad opportunity", grant.manual_review_reason)

    def test_connector_registry_includes_wave_sources(self) -> None:
        self.assertIs(CONNECTOR_CLASSES["chas-zmin"], ChasZminConnector)
        self.assertIs(CONNECTOR_CLASSES["eufundingportal-eu"], EUFundingPortalEuConnector)
        self.assertIs(CONNECTOR_CLASSES["hromady"], HromadyConnector)
        self.assertIs(CONNECTOR_CLASSES["nipo"], NipoConnector)
        self.assertIs(CONNECTOR_CLASSES["grant-market"], GrantMarketConnector)
        self.assertIs(CONNECTOR_CLASSES["fundsforngos"], FundsForNgosConnector)
        self.assertIs(CONNECTOR_CLASSES["opportunitydesk"], OpportunityDeskConnector)

    def test_ingestion_service_saves_snapshots_grants_and_job(self) -> None:
        feed_url = "https://www.prostir.ua/category/grants/feed/"
        detail_url = "https://www.prostir.ua/grant/test-grant/"
        self.source(
            slug="prostir",
            access_strategy=AccessStrategy.RSS,
            base_url="https://www.prostir.ua",
            feed_url=feed_url,
        )
        fake_http = FakeHttpClient(
            {
                feed_url: html_response(feed_url, "prostir/feed.xml", "application/rss+xml"),
                detail_url: html_response(detail_url, "prostir/detail.html"),
            }
        )
        service = IngestionService(
            repository=self.repository,
            connector_classes={"prostir": CONNECTOR_CLASSES["prostir"]},
            http_client_factory=lambda _rate_limit: fake_http,
        )

        first = service.run_source("prostir", limit=20)
        second = service.run_source("prostir", limit=20)
        grant_count = self.session.scalar(select(func.count(Grant.id)))
        discovered_count = self.session.scalar(select(func.count(DiscoveredGrantItem.id)))
        discovered_item = self.session.scalar(select(DiscoveredGrantItem))

        self.assertEqual(first.status, JobStatus.SUCCESS.value)
        self.assertEqual(first.created_count, 1)
        self.assertEqual(second.updated_count, 0)
        self.assertEqual(second.skipped_count, 1)
        self.assertEqual(grant_count, 1)
        self.assertEqual(discovered_count, 1)
        self.assertEqual(discovered_item.detail_fetch_status, DetailFetchStatus.SKIPPED_KNOWN.value)

    def test_ingestion_service_saves_wave1_wp_rest_source(self) -> None:
        api_url = "https://chaszmin.com.ua/wp-json/wp/v2/posts"
        self.source(
            slug="chas-zmin",
            access_strategy=AccessStrategy.WP_REST,
            base_url="https://chaszmin.com.ua",
            api_url=api_url,
            feed_url="https://chaszmin.com.ua/feed/",
        )
        fake_http = FakeHttpClient({api_url: json_response(api_url, "chas_zmin/posts.json")})
        service = IngestionService(
            repository=self.repository,
            connector_classes={"chas-zmin": CONNECTOR_CLASSES["chas-zmin"]},
            http_client_factory=lambda _rate_limit: fake_http,
        )

        summary = service.run_source("chas-zmin", limit=20)
        grant_count = self.session.scalar(select(func.count(Grant.id)))
        discovered_count = self.session.scalar(select(func.count(DiscoveredGrantItem.id)))

        self.assertEqual(summary.status, JobStatus.SUCCESS.value)
        self.assertEqual(summary.created_count, 1)
        self.assertEqual(grant_count, 1)
        self.assertEqual(discovered_count, 1)

    def test_ingestion_service_saves_wave2_sitemap_source(self) -> None:
        sitemap_url = "https://grant.market/sitemap.xml"
        detail_url = "https://grant.market/opp/ebrd-consulting"
        self.source(
            slug="grant-market",
            access_strategy=AccessStrategy.SITEMAP_HTML,
            base_url="https://grant.market",
            sitemap_url=sitemap_url,
        )
        fake_http = FakeHttpClient(
            {
                sitemap_url: html_response(sitemap_url, "grant_market/sitemap.xml", "application/xml"),
                detail_url: html_response(detail_url, "grant_market/detail.html"),
            }
        )
        service = IngestionService(
            repository=self.repository,
            connector_classes={"grant-market": CONNECTOR_CLASSES["grant-market"]},
            http_client_factory=lambda _rate_limit: fake_http,
        )

        summary = service.run_source("grant-market", limit=20)
        grant_count = self.session.scalar(select(func.count(Grant.id)))
        discovered_count = self.session.scalar(select(func.count(DiscoveredGrantItem.id)))

        self.assertEqual(summary.status, JobStatus.SUCCESS.value)
        self.assertEqual(summary.created_count, 1)
        self.assertEqual(grant_count, 1)
        self.assertEqual(discovered_count, 1)

    def test_incremental_mode_skips_known_items_for_all_configured_connectors(self) -> None:
        for case in source_fixture_cases():
            with self.subTest(source=case["slug"]):
                self.tearDown()
                self.setUp()
                source_kwargs = {
                    key: case.get(key)
                    for key in ("slug", "access_strategy", "base_url", "list_url", "api_url", "feed_url", "sitemap_url")
                    if case.get(key) is not None
                }
                self.source(**source_kwargs)
                fake_http = FakeHttpClient(case["responses"])
                service = IngestionService(
                    repository=self.repository,
                    connector_classes={case["slug"]: CONNECTOR_CLASSES[case["slug"]]},
                    http_client_factory=lambda _rate_limit, client=fake_http: client,
                )

                first = service.run_source(case["slug"], limit=1, mode="backfill")
                second = service.run_source(case["slug"], limit=1, mode="incremental")
                grant_count = self.session.scalar(select(func.count(Grant.id)))
                snapshot_count = self.session.scalar(select(func.count(RawGrantSnapshot.id)))
                discovered_count = self.session.scalar(select(func.count(DiscoveredGrantItem.id)))
                discovered_item = self.session.scalar(select(DiscoveredGrantItem))

                self.assertEqual(first.status, JobStatus.SUCCESS.value)
                self.assertEqual(first.processed_count, 1)
                self.assertEqual(first.created_count, 1)
                self.assertEqual(second.status, JobStatus.SUCCESS.value)
                self.assertEqual(second.processed_count, 1)
                self.assertEqual(second.skipped_count, 1)
                self.assertEqual(second.created_count, 0)
                self.assertEqual(second.updated_count, 0)
                self.assertEqual(grant_count, 1)
                self.assertEqual(snapshot_count, 1)
                self.assertEqual(discovered_count, 1)
                self.assertEqual(discovered_item.detail_fetch_status, DetailFetchStatus.SKIPPED_KNOWN.value)
                self.assertEqual(discovered_item.discovery_status, "known")
                self.assertEqual(discovered_item.discovery_metadata["last_skip_reason"], "known_discovered_item")
                self.assertEqual(second.job.job_metadata["discovered_count"], 1)
                self.assertEqual(second.job.job_metadata["new_discovered_count"], 0)
                self.assertEqual(second.job.job_metadata["known_discovered_count"], 1)
                self.assertGreaterEqual(fake_http.count_calls(case["listing_method"], case["listing_url"]), 2)
                for detail_url in case["detail_urls"]:
                    self.assertEqual(fake_http.count_calls("GET", detail_url), 1)

    def test_incremental_mode_refreshes_known_open_items_when_due(self) -> None:
        feed_url = "https://www.prostir.ua/category/grants/feed/"
        detail_url = "https://www.prostir.ua/grant/test-grant/"
        source = self.source(
            slug="prostir",
            access_strategy=AccessStrategy.RSS,
            base_url="https://www.prostir.ua",
            feed_url=feed_url,
        )
        fake_http = FakeHttpClient(
            {
                feed_url: html_response(feed_url, "prostir/feed.xml", "application/rss+xml"),
                detail_url: html_response(detail_url, "prostir/detail.html"),
            }
        )
        service = IngestionService(
            repository=self.repository,
            connector_classes={"prostir": CONNECTOR_CLASSES["prostir"]},
            http_client_factory=lambda _rate_limit: fake_http,
        )

        first = service.run_source("prostir", limit=1, mode="backfill")
        grant = self.session.scalar(select(Grant))
        grant.status = "open"
        grant.updated_at = datetime.now(UTC) - timedelta(days=8)
        self.session.flush()

        second = service.run_source("prostir", limit=1, mode="incremental")
        snapshot_count = self.session.scalar(select(func.count(RawGrantSnapshot.id)))
        discovered_item = self.session.scalar(select(DiscoveredGrantItem))

        self.assertEqual(first.status, JobStatus.SUCCESS.value)
        self.assertEqual(second.status, JobStatus.SUCCESS.value)
        self.assertEqual(second.processed_count, 1)
        self.assertEqual(second.updated_count, 1)
        self.assertEqual(second.skipped_count, 0)
        self.assertEqual(snapshot_count, 1)
        self.assertEqual(discovered_item.detail_fetch_status, DetailFetchStatus.FETCHED.value)
        self.assertEqual(discovered_item.discovery_metadata["last_refresh_reason"], "known_item_due_for_refresh")
        self.assertEqual(second.job.job_metadata["refresh_due_count"], 1)
        self.assertEqual(second.job.job_metadata["refreshed_known_count"], 1)
        self.assertEqual(second.job.job_metadata["skipped_known_count"], 0)
        self.assertEqual(second.job.job_metadata["refresh_policy"]["open_interval_days"], 7)
        self.assertGreaterEqual(fake_http.count_calls("GET", feed_url), 2)
        self.assertEqual(fake_http.count_calls("GET", detail_url), 2)

    def test_incremental_mode_refreshes_due_item_not_present_in_current_listing(self) -> None:
        feed_url = "https://www.prostir.ua/category/grants/feed/"
        detail_url = "https://www.prostir.ua/grant/test-grant/"
        self.source(
            slug="prostir",
            access_strategy=AccessStrategy.RSS,
            base_url="https://www.prostir.ua",
            feed_url=feed_url,
        )
        fake_http = FakeHttpClient(
            {
                feed_url: html_response(feed_url, "prostir/feed.xml", "application/rss+xml"),
                detail_url: html_response(detail_url, "prostir/detail.html"),
            }
        )
        service = IngestionService(
            repository=self.repository,
            connector_classes={"prostir": CONNECTOR_CLASSES["prostir"]},
            http_client_factory=lambda _rate_limit: fake_http,
        )

        service.run_source("prostir", limit=1, mode="backfill")
        grant = self.session.scalar(select(Grant))
        grant.status = "open"
        grant.updated_at = datetime.now(UTC) - timedelta(days=8)
        self.session.flush()
        fake_http.responses[feed_url] = HttpResponse(
            url=feed_url,
            status_code=200,
            content_type="application/rss+xml",
            text="<?xml version='1.0'?><rss><channel></channel></rss>",
        )

        second = service.run_source("prostir", limit=1, mode="incremental")
        discovered_item = self.session.scalar(select(DiscoveredGrantItem))

        self.assertEqual(second.status, JobStatus.SUCCESS.value)
        self.assertEqual(second.processed_count, 1)
        self.assertEqual(second.updated_count, 1)
        self.assertEqual(second.job.job_metadata["discovered_count"], 0)
        self.assertEqual(second.job.job_metadata["refresh_due_candidate_count"], 1)
        self.assertEqual(second.job.job_metadata["refresh_due_count"], 1)
        self.assertEqual(second.job.job_metadata["refreshed_known_count"], 1)
        self.assertEqual(discovered_item.discovery_metadata["refresh_source"], "due_item_not_in_listing")
        self.assertEqual(fake_http.count_calls("GET", feed_url), 2)
        self.assertEqual(fake_http.count_calls("GET", detail_url), 2)


if __name__ == "__main__":
    unittest.main()
