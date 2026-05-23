from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, DiscoveredGrantItem, Grant, JobStatus, Source
from grant_tool.db.repositories import GrantRepository
from grant_tool.ingestion.connectors import (
    ChasZminConnector,
    CONNECTOR_CLASSES,
    DiiaBusinessConnector,
    EUFundingPortalEuConnector,
    EUFundingConnector,
    GurtConnector,
    HromadyConnector,
    ProstirConnector,
)
from grant_tool.ingestion.http import HttpResponse
from grant_tool.ingestion.service import IngestionService
from grant_tool.ingestion.types import DetailFetchStatus


FIXTURES = Path(__file__).parent / "fixtures"


class FakeHttpClient:
    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self.responses = responses

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> HttpResponse:
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
        if url not in self.responses:
            raise AssertionError(f"Unexpected POST URL: {url}")
        return self.responses[url]

    def close(self) -> None:
        pass


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

    def test_connector_registry_includes_wave1_sources(self) -> None:
        self.assertIs(CONNECTOR_CLASSES["chas-zmin"], ChasZminConnector)
        self.assertIs(CONNECTOR_CLASSES["eufundingportal-eu"], EUFundingPortalEuConnector)
        self.assertIs(CONNECTOR_CLASSES["hromady"], HromadyConnector)

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


if __name__ == "__main__":
    unittest.main()
