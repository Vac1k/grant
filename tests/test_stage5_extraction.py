from __future__ import annotations

import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, Grant, JobStatus
from grant_tool.db.repositories import GrantRepository
from grant_tool.extraction import FeatureExtractionService
from grant_tool.ingestion.connectors import CONNECTOR_CLASSES
from grant_tool.ingestion.service import IngestionService
from grant_tool.ingestion.types import FetchedGrant, NormalizedGrantDraft

from tests.test_stage3_ingestion import FakeHttpClient, html_response


FIXTURES = Path(__file__).parent / "fixtures"


class Stage5ExtractionTestCase(unittest.TestCase):
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

    def test_deterministic_extraction_builds_feature_card(self) -> None:
        draft = NormalizedGrantDraft(
            source_url="https://example.org/grants/ai-support",
            title="AI support for Ukrainian SMEs",
            description_text=(
                "Deadline: 31.12.2026. Funding up to EUR 500 000 for Ukrainian SMEs and startups. "
                "Eligible applicants are technology companies working with artificial intelligence and innovation. "
                "Consortium partners are recommended. Co-financing may be required."
            ),
        )

        FeatureExtractionService().enrich_draft(draft, source_slug="example")

        self.assertEqual(draft.status, "open")
        self.assertEqual(draft.currency, "EUR")
        self.assertEqual(str(draft.funding_amount_max), "500000.00")
        self.assertIn("SME", draft.applicant_types)
        self.assertIn("startup", draft.applicant_types)
        self.assertIn("AI", draft.topics)
        self.assertIn("innovation", draft.topics)
        self.assertIn("Ukraine", draft.countries)
        self.assertTrue(draft.consortium_required)
        self.assertTrue(draft.cofinancing_required)
        self.assertIn("feature_card", draft.extraction_metadata)
        self.assertGreaterEqual(draft.extraction_confidence, 0)

    def test_generic_title_is_recovered_from_url_and_marked_for_review(self) -> None:
        draft = NormalizedGrantDraft(
            source_url="https://business.diia.gov.ua/finance/programs/programa_es_gorizont_evropa_2021_2027",
            title="Дія Бізнес",
            description_text="Дія Бізнес",
        )

        FeatureExtractionService().enrich_draft(draft, source_slug="diia-business")

        self.assertEqual(draft.title, "Programa es gorizont evropa 2021 2027")
        self.assertTrue(draft.needs_manual_review)
        self.assertIn("very short extracted text", draft.manual_review_reason or "")

    def test_ingestion_service_applies_stage5_features(self) -> None:
        feed_url = "https://www.prostir.ua/category/grants/feed/"
        detail_url = "https://www.prostir.ua/grant/test-grant/"
        self.repository.upsert_source(
            slug="prostir",
            name="prostir",
            base_url="https://www.prostir.ua",
            access_strategy=AccessStrategy.RSS,
            feed_url=feed_url,
            rate_limit_seconds=0,
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

        summary = service.run_source("prostir", limit=20)
        grant = self.session.scalar(select(Grant))

        self.assertEqual(summary.status, JobStatus.SUCCESS.value)
        self.assertIsNotNone(grant)
        self.assertIn("company", grant.applicant_types)
        self.assertIn("AI", grant.topics)
        self.assertIn("innovation", grant.topics)
        self.assertEqual(grant.currency, "UAH")
        self.assertEqual(str(grant.funding_amount_max), "500000.00")
        self.assertIn("stage_5", grant.extraction_metadata["stage"])

    def test_run_existing_updates_stored_grants_and_records_job(self) -> None:
        source = self.repository.upsert_source(
            slug="manual-test",
            name="manual-test",
            base_url="https://example.org",
            access_strategy=AccessStrategy.MANUAL,
            rate_limit_seconds=0,
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://example.org/grants/community",
            title="Community grant",
            description_text=(
                "Грант для місцевих громадських організацій. Кінцевий термін подання: 31.12.2026. "
                "Підтримка community та humanitarian ініціатив, бюджет 20 000 USD."
            ),
        )
        self.session.flush()

        summary = FeatureExtractionService(repository=self.repository).run_existing(limit=10)

        self.assertEqual(summary.job.status, JobStatus.SUCCESS.value)
        self.assertEqual(summary.updated_count, 1)
        self.assertIn("NGO", grant.applicant_types)
        self.assertIn("community", grant.topics)
        self.assertIn("humanitarian", grant.topics)
        self.assertEqual(grant.currency, "USD")


if __name__ == "__main__":
    unittest.main()
