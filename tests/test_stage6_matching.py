from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, Grant, GrantClientMatch
from grant_tool.db.repositories import GrantRepository
from grant_tool.matching import ShortlistMatchingService


class Stage6MatchingTestCase(unittest.TestCase):
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
        self.source = self.repository.upsert_source(
            slug="test-source",
            name="Test Source",
            base_url="https://example.org",
            access_strategy=AccessStrategy.API,
        )

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_stage6_shortlist_saves_ranked_matches_and_filters_obvious_mismatches(self) -> None:
        client = self.repository.upsert_client_profile(
            slug="ukrainian-ai-sme",
            name="Ukrainian AI SME",
            country="Ukraine",
            sector="technology",
            organization_type="SME company",
            technologies=["AI", "machine learning"],
            target_topics=["AI", "innovation"],
            excluded_topics=["culture"],
        )
        matching_grant = self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/ai",
            title="AI innovation grant for Ukrainian SMEs",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            summary="Funding for Ukrainian technology companies using AI and machine learning.",
            countries=["Ukraine"],
            applicant_types=["SME"],
            topics=["AI", "innovation"],
            extraction_confidence=Decimal("0.9000"),
        )
        self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/closed",
            title="Closed AI grant",
            status="closed",
            countries=["Ukraine"],
            applicant_types=["SME"],
            topics=["AI"],
        )
        self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/ngo",
            title="NGO culture programme",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            countries=["Ukraine"],
            applicant_types=["NGO"],
            topics=["culture"],
        )
        self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/nonprofit-only",
            title="AI grant for non-profit organisations",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            summary="Eligible applicants are non-profit organisations and charitable foundations.",
            countries=["Ukraine"],
            applicant_types=["company", "NGO"],
            topics=["AI", "innovation"],
        )
        self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/training",
            title="AI training for companies",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            countries=["Ukraine"],
            applicant_types=["company"],
            topics=["AI", "innovation"],
            opportunity_type="training",
            support_type="training",
        )
        self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/camp",
            title="Набір на AI табір для підприємців",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            countries=["Ukraine"],
            applicant_types=["company"],
            topics=["AI", "innovation"],
        )
        self.repository.save_application_history(
            client_profile_id=client.id,
            client_name=client.name,
            grant_title="Previous AI innovation grant",
            grant_source="test-source",
            result="lost",
            topics=["AI", "innovation"],
            reusable_materials="Concept note and budget",
            similarity_weight=Decimal("1.200"),
        )

        summary = ShortlistMatchingService(repository=self.repository).run(top_n=5, min_score=Decimal("0.1000"))
        match = self.session.scalar(select(GrantClientMatch).where(GrantClientMatch.grant_id == matching_grant.id))

        self.assertEqual(summary.clients_count, 1)
        self.assertEqual(summary.grants_count, 6)
        self.assertEqual(summary.evaluated_count, 6)
        self.assertEqual(summary.saved_count, 1)
        self.assertEqual(summary.filtered_count, 5)
        self.assertIsNotNone(match)
        self.assertEqual(match.rank, 1)
        self.assertTrue(match.hard_filter_passed)
        self.assertGreater(match.score, Decimal("0.7000"))
        self.assertGreater(match.keyword_score, Decimal("0.7000"))
        self.assertGreater(match.history_score, Decimal("0.5000"))
        self.assertIn("topic fit", match.explanation)
        self.assertEqual(match.evidence["history"]["matched_history"][0]["result"], "lost")

    def test_stage6_unknown_fields_create_manual_checks_but_do_not_block_shortlist(self) -> None:
        self.repository.upsert_client_profile(
            slug="ukraine-company",
            name="Ukraine Company",
            country="Ukraine",
            organization_type="company",
            technologies=["resilience"],
            target_topics=["humanitarian"],
        )
        grant = self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/unknown",
            title="Humanitarian resilience support",
            status="unknown",
            summary="Support for resilience projects in Ukraine.",
            countries=[],
            applicant_types=[],
            topics=["humanitarian"],
            extraction_confidence=Decimal("0.6000"),
        )

        summary = ShortlistMatchingService(repository=self.repository).run(top_n=3, min_score=Decimal("0.1000"))
        match = self.session.scalar(select(GrantClientMatch).where(GrantClientMatch.grant_id == grant.id))

        self.assertEqual(summary.saved_count, 1)
        self.assertIsNotNone(match)
        self.assertTrue(match.hard_filter_passed)
        self.assertIn("grant status is unknown", match.manual_checks)
        self.assertIn("grant countries missing", match.manual_checks)
        self.assertIn("grant applicant types missing", match.manual_checks)

    def test_stage6_client_slug_filters_clients(self) -> None:
        client = self.repository.upsert_client_profile(
            slug="target-client",
            name="Target Client",
            country="Ukraine",
            organization_type="company",
            target_topics=["AI"],
        )
        self.repository.upsert_client_profile(
            slug="other-client",
            name="Other Client",
            country="Ukraine",
            organization_type="company",
            target_topics=["AI"],
        )
        self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/ai-only",
            title="AI support",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            countries=["Ukraine"],
            applicant_types=["company"],
            topics=["AI"],
        )

        summary = ShortlistMatchingService(repository=self.repository).run(
            client_slug=client.slug,
            top_n=5,
            min_score=Decimal("0.1000"),
        )
        saved_count = self.session.scalar(select(func.count(GrantClientMatch.id)))

        self.assertEqual(summary.clients_count, 1)
        self.assertEqual(saved_count, 1)


if __name__ == "__main__":
    unittest.main()
