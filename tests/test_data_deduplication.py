from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.data_quality import QualityFlag, evaluate_grant_quality_contract
from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, GrantClientMatch
from grant_tool.db.repositories import GrantRepository
from grant_tool.deduplication import GrantDeduplicationService
from grant_tool.matching import ShortlistMatchingService


class DataDeduplicationTestCase(unittest.TestCase):
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
        self.eu_source = self.repository.upsert_source(
            slug="eu-funding",
            name="EU Funding",
            base_url="https://ec.europa.eu",
            access_strategy=AccessStrategy.API,
        )
        self.aggregator_source = self.repository.upsert_source(
            slug="eufundingportal-eu",
            name="EU Funding Portal",
            base_url="https://eufundingportal.eu",
            access_strategy=AccessStrategy.WP_REST,
        )
        self.prostir_source = self.repository.upsert_source(
            slug="prostir",
            name="Prostir",
            base_url="https://www.prostir.ua",
            access_strategy=AccessStrategy.RSS,
        )

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_exact_duplicate_candidate_uses_canonical_url_without_deleting_records(self) -> None:
        first = self.repository.upsert_grant(
            source_id=self.prostir_source.id,
            source_url="https://www.prostir.ua/grant/ai-support?utm_source=newsletter",
            title="AI innovation grant for SMEs",
            status="open",
            summary="Funding for Ukrainian SMEs building AI products.",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            countries=["Ukraine"],
            applicant_types=["SME"],
            topics=["AI", "innovation"],
        )
        second = self.repository.upsert_grant(
            source_id=self.prostir_source.id,
            source_url="https://www.prostir.ua/grant/ai-support",
            title="AI innovation grant for SMEs",
            status="open",
            summary="Funding for Ukrainian SMEs building AI products.",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            countries=["Ukraine"],
            applicant_types=["SME"],
            topics=["AI", "innovation"],
        )

        summary = GrantDeduplicationService(repository=self.repository).run()

        self.assertEqual(summary.processed_count, 2)
        self.assertEqual(summary.duplicate_group_count, 1)
        self.assertEqual(summary.duplicate_record_count, 1)
        first_dedup = first.extraction_metadata["deduplication"]
        second_dedup = second.extraction_metadata["deduplication"]
        self.assertEqual(first_dedup["duplicate_group_id"], second_dedup["duplicate_group_id"])
        self.assertTrue(first_dedup["is_duplicate"] or second_dedup["is_duplicate"])
        self.assertIn("same_canonical_or_application_url", summary.candidates[0].reasons)

    def test_fuzzy_duplicate_marks_aggregator_as_non_primary_and_matching_filters_it(self) -> None:
        official = self.repository.upsert_grant(
            source_id=self.eu_source.id,
            source_record_id="HORIZON-AI-2026",
            source_url="https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/HORIZON-AI-2026",
            title="Horizon Europe AI Innovation Grant",
            status="open",
            summary="Funding for companies building artificial intelligence products in Europe.",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            funder_name="European Commission",
            funding_amount_max=Decimal("100000.00"),
            funding_amount_text="EUR 100 000",
            currency="EUR",
            countries=["EU"],
            applicant_types=["company"],
            topics=["AI", "innovation"],
        )
        aggregator = self.repository.upsert_grant(
            source_id=self.aggregator_source.id,
            source_url="https://eufundingportal.eu/horizon-europe-ai-innovation-grants/",
            title="Horizon Europe AI innovation grants",
            status="open",
            summary="EU funding opportunity for companies working with AI innovation.",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            funder_name="European Commission",
            funding_amount_max=Decimal("100000.00"),
            funding_amount_text="EUR 100 000",
            currency="EUR",
            countries=["EU"],
            applicant_types=["company"],
            topics=["AI", "innovation"],
        )
        self.repository.upsert_grant(
            source_id=self.prostir_source.id,
            source_url="https://www.prostir.ua/grant/culture/",
            title="Culture grant for NGOs",
            status="open",
            summary="Funding for cultural projects.",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            countries=["Ukraine"],
            applicant_types=["NGO"],
            topics=["culture"],
        )
        client = self.repository.upsert_client_profile(
            slug="ai-company",
            name="AI Company",
            country="Ukraine",
            organization_type="company",
            technologies=["AI"],
            target_topics=["AI", "innovation"],
        )

        summary = GrantDeduplicationService(repository=self.repository).run()
        official_dedup = official.extraction_metadata["deduplication"]
        aggregator_dedup = aggregator.extraction_metadata["deduplication"]
        official_quality = evaluate_grant_quality_contract(official)
        aggregator_candidate = ShortlistMatchingService(repository=self.repository).score(
            grant=aggregator,
            client=client,
        )
        match_summary = ShortlistMatchingService(repository=self.repository).run(top_n=5, min_score=Decimal("0.1000"))
        official_match = self.session.scalar(select(GrantClientMatch).where(GrantClientMatch.grant_id == official.id))
        aggregator_match = self.session.scalar(select(GrantClientMatch).where(GrantClientMatch.grant_id == aggregator.id))

        self.assertEqual(summary.duplicate_group_count, 1)
        self.assertEqual(summary.duplicate_record_count, 1)
        self.assertFalse(official_dedup["is_duplicate"])
        self.assertTrue(official_dedup["is_primary"])
        self.assertTrue(aggregator_dedup["is_duplicate"])
        self.assertEqual(aggregator_dedup["primary_grant_id"], str(official.id))
        self.assertIn(QualityFlag.POSSIBLE_DUPLICATE, official_quality.flags)
        self.assertFalse(aggregator_candidate.hard_filter_passed)
        self.assertIn(f"duplicate_grant:{official.id}", aggregator_candidate.filter_reasons)
        self.assertEqual(match_summary.grants_count, 3)
        self.assertIsNotNone(official_match)
        self.assertIsNone(aggregator_match)


if __name__ == "__main__":
    unittest.main()
