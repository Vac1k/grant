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
from grant_tool.ingestion.utils import extract_deadline, status_from_deadline

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

    def test_training_page_is_not_classified_as_grant(self) -> None:
        draft = NormalizedGrantDraft(
            source_url="https://www.prostir.ua/?grants=tochka-startu",
            title="Точка старту: 3-денний тренінг для молоді",
            description_text=(
                "Актуально до: 25.05.26. SILab Ukraine запрошує на 3-денний тренінг "
                "для молоді з підприємництва."
            ),
            opportunity_type="grant",
            support_type="grant",
        )

        FeatureExtractionService().enrich_draft(draft, source_slug="prostir")

        self.assertEqual(draft.status, "open")
        self.assertEqual(draft.deadline_at.date().isoformat(), "2026-05-25")
        self.assertEqual(draft.opportunity_type, "training")
        self.assertEqual(draft.support_type, "training")

    def test_eu_multiple_cutoffs_use_next_future_deadline(self) -> None:
        draft = NormalizedGrantDraft(
            source_url="https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/CREA-MEDIA-2026-FILMOVE",
            title="Films on the Move",
            status="unknown",
        )
        raw_payload = {
            "metadata": {
                "deadlineDate": ['{"deadlineDates":["2026-03-19","2026-07-16"]}'],
                "budgetOverview": ['{"budgetTopicActionMap":{"111805":[{"deadlineDates":["2026-03-19","2026-07-16"]}]}}'],
            }
        }

        FeatureExtractionService().enrich_draft(draft, source_slug="eu-funding", raw_payload=raw_payload)

        self.assertEqual(draft.status, "open")
        self.assertEqual(draft.deadline_at.date().isoformat(), "2026-07-16")

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

    def test_deadline_parser_ignores_publication_date_and_reads_ukrainian_month(self) -> None:
        text = (
            "ГУРТ шукає партнерів для створення осередків самодопомоги 20.05.2026. "
            "Оцінювання ЗАЯВКИ, яку треба заповнити до 04 червня 2026. "
            "Навчання менеджера осередку 19-20 червня 2026."
        )

        deadline_at, deadline_text = extract_deadline(text)

        self.assertIsNotNone(deadline_at)
        self.assertEqual(deadline_at.date().isoformat(), "2026-06-04")
        self.assertIn("заповнити до 04 червня 2026", deadline_text)
        self.assertEqual(status_from_deadline(deadline_at), "open")

    def test_deadline_parser_reads_two_digit_year_and_not_later_phrase(self) -> None:
        prostir_text = (
            "15.05.2026 - 25.06.2026 Конкурс грантів. "
            "Актуально до: 25.06.26 Зафіксувати у Google календарі."
        )
        gurt_text = (
            "Конкурс на розробку моделей працевлаштування ветеранів з інвалідністю 19.05.2026. "
            "Заявки мають бути отримані не пізніше 10 червня 2026 р., 23:59 за київським часом."
        )

        prostir_deadline, _ = extract_deadline(prostir_text)
        gurt_deadline, _ = extract_deadline(gurt_text)

        self.assertEqual(prostir_deadline.date().isoformat(), "2026-06-25")
        self.assertEqual(gurt_deadline.date().isoformat(), "2026-06-10")
        self.assertEqual(status_from_deadline(prostir_deadline), "open")
        self.assertEqual(status_from_deadline(gurt_deadline), "open")


if __name__ == "__main__":
    unittest.main()
