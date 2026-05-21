from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, GrantClientMatch
from grant_tool.db.repositories import GrantRepository
from grant_tool.embeddings import EmbeddingService, EmbeddingTarget
from grant_tool.matching import ShortlistMatchingService


class Stage7EmbeddingTestCase(unittest.TestCase):
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

    def test_stage7_generates_embeddings_for_all_profile_types(self) -> None:
        client = self.repository.upsert_client_profile(
            slug="ai-client",
            name="AI Client",
            country="Ukraine",
            organization_type="SME company",
            technologies=["AI", "machine learning"],
            target_topics=["AI", "innovation"],
        )
        grant = self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/ai-grant",
            title="AI innovation grant",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            summary="Funding for AI and machine learning products.",
            countries=["Ukraine"],
            applicant_types=["SME"],
            topics=["AI", "innovation"],
        )
        history = self.repository.save_application_history(
            client_profile_id=client.id,
            client_name=client.name,
            grant_title="Previous AI grant",
            result="lost",
            topics=["AI"],
            project_summary="AI product development",
            reusable_materials="Pitch deck",
        )

        summary = EmbeddingService(repository=self.repository).run(target=EmbeddingTarget.ALL, batch_size=2)

        self.assertEqual(summary.job.status, "success")
        self.assertEqual(summary.processed_count, 3)
        self.assertEqual(len(grant.embedding), 1536)
        self.assertEqual(len(client.embedding), 1536)
        self.assertEqual(len(history.embedding), 1536)
        self.assertEqual(grant.embedding_model, "local-hash-embedding-v1")
        self.assertIn("AI innovation grant", grant.embedding_text)
        self.assertIn("AI Client", client.embedding_text)
        self.assertIn("Previous AI grant", history.embedding_text)

    def test_stage7_vector_score_is_saved_in_matching_results(self) -> None:
        client = self.repository.upsert_client_profile(
            slug="ai-client",
            name="AI Client",
            country="Ukraine",
            organization_type="SME company",
            technologies=["AI"],
            target_topics=["AI"],
        )
        grant = self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/ai-grant",
            title="AI innovation grant",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            summary="AI funding for Ukrainian SME companies.",
            countries=["Ukraine"],
            applicant_types=["SME"],
            topics=["AI"],
            extraction_confidence=Decimal("0.9000"),
        )
        self.repository.save_application_history(
            client_profile_id=client.id,
            client_name=client.name,
            grant_title="AI innovation history",
            result="rejected",
            topics=["AI"],
            project_summary="AI funding for Ukrainian companies",
            reusable_materials="Reusable budget",
        )
        EmbeddingService(repository=self.repository).run(target=EmbeddingTarget.ALL)

        summary = ShortlistMatchingService(repository=self.repository).run(
            client_slug=client.slug,
            top_n=5,
            min_score=Decimal("0.1000"),
            use_vector=True,
        )
        match = self.session.scalar(select(GrantClientMatch).where(GrantClientMatch.grant_id == grant.id))

        self.assertEqual(summary.saved_count, 1)
        self.assertIsNotNone(match)
        self.assertIsNotNone(match.vector_score)
        self.assertGreater(match.vector_score, Decimal("0.0000"))
        self.assertEqual(match.match_metadata["score_breakdown"]["vector_score"], str(match.vector_score))
        self.assertGreaterEqual(
            match.score,
            Decimal(match.match_metadata["score_breakdown"]["stage6_fallback_score"]),
        )
        self.assertTrue(match.evidence["vector"]["enabled"])

    def test_stage7_matching_without_embeddings_falls_back_to_stage6_scores(self) -> None:
        client = self.repository.upsert_client_profile(
            slug="ai-client",
            name="AI Client",
            country="Ukraine",
            organization_type="SME company",
            target_topics=["AI"],
        )
        grant = self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/ai-grant",
            title="AI support",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            countries=["Ukraine"],
            applicant_types=["SME"],
            topics=["AI"],
        )

        ShortlistMatchingService(repository=self.repository).run(
            client_slug=client.slug,
            top_n=5,
            min_score=Decimal("0.1000"),
            use_vector=True,
        )
        match = self.session.scalar(select(GrantClientMatch).where(GrantClientMatch.grant_id == grant.id))

        self.assertIsNotNone(match)
        self.assertIsNone(match.vector_score)
        self.assertIsNone(match.match_metadata["score_breakdown"]["vector_score"])
        self.assertEqual(match.evidence["vector"]["reason"], "missing embeddings")


if __name__ == "__main__":
    unittest.main()
