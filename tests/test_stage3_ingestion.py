from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, Grant, JobStatus, Source
from grant_tool.db.repositories import GrantRepository
from grant_tool.ingestion.connectors import (
    CONNECTOR_CLASSES,
    DiiaBusinessConnector,
    EUFundingConnector,
    GurtConnector,
    ProstirConnector,
)
from grant_tool.ingestion.http import HttpResponse
from grant_tool.ingestion.service import IngestionService


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

    def test_diia_business_connector_parses_sitemap_and_detail(self) -> None:
        sitemap_url = "https://www.business.diia.gov.ua/sitemap.xml"
        detail_url = "https://www.business.diia.gov.ua/finance/programs/test-program"
        source = self.source(
            slug="diia-business",
            access_strategy=AccessStrategy.SITEMAP_HTML,
            base_url="https://www.business.diia.gov.ua",
            sitemap_url=sitemap_url,
        )
        connector = DiiaBusinessConnector(
            source=source,
            http_client=FakeHttpClient(
                {
                    sitemap_url: html_response(sitemap_url, "diia_business/sitemap.xml", "application/xml"),
                    detail_url: html_response(detail_url, "diia_business/detail.html"),
                }
            ),
        )

        result = connector.run(limit=20)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.grants), 1)
        grant = result.grants[0].normalized
        self.assertEqual(grant.opportunity_type, "business_support")
        self.assertEqual(grant.support_type, "finance_programme")
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

        self.assertEqual(first.status, JobStatus.SUCCESS.value)
        self.assertEqual(first.created_count, 1)
        self.assertEqual(second.updated_count, 1)
        self.assertEqual(grant_count, 1)


if __name__ == "__main__":
    unittest.main()
