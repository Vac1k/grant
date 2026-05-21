from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, GrantClientMatch
from grant_tool.db.repositories import GrantRepository
from grant_tool.explanations import MatchExplanationService


class Stage8ExplanationTestCase(unittest.TestCase):
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

    def _seed_match(self) -> GrantClientMatch:
        client = self.repository.upsert_client_profile(
            slug="ai-client",
            name="AI Client",
            country="Ukraine",
            sector="AI automation",
            organization_type="SME company",
            technologies=["AI", "machine learning"],
            target_topics=["AI", "innovation"],
            product_description="AI automation product for customer support.",
        )
        grant = self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://example.org/ai-grant",
            title="AI innovation grant",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            summary="Funding for AI products developed by Ukrainian SMEs.",
            countries=["Ukraine"],
            applicant_types=["SME"],
            topics=["AI", "innovation"],
            eligibility_text="Eligible applicants are Ukrainian SMEs.",
            extraction_metadata={"feature_card": {"title": "AI innovation grant", "topics": ["AI"]}},
        )
        self.repository.save_application_history(
            client_profile_id=client.id,
            client_name=client.name,
            grant_title="Previous AI grant",
            result="lost",
            topics=["AI"],
            project_summary="AI customer support automation",
            reusable_materials="Concept note and budget",
        )
        match_run = self.repository.create_match_run(name="Stage 8 test run", status="success")
        return self.repository.save_match_result(
            match_run_id=match_run.id,
            grant_id=grant.id,
            client_profile_id=client.id,
            score=Decimal("0.4200"),
            rank=1,
            keyword_score=Decimal("0.3000"),
            vector_score=Decimal("0.5000"),
            history_score=Decimal("0.3000"),
            manual_checks=["deadline missing"],
            evidence={
                "keyword": {"topic_hits": ["ai"], "technology_hits": ["machine learning"], "applicant_hit": True},
                "vector": {"enabled": True, "grant_client_similarity": "0.5000"},
                "history": {
                    "matched_history": [
                        {
                            "grant_title": "Previous AI grant",
                            "result": "lost",
                            "topic_hits": ["ai"],
                            "reusable_materials": True,
                        }
                    ]
                },
            },
            match_metadata={
                "score_breakdown": {
                    "keyword_score": "0.3000",
                    "vector_score": "0.5000",
                    "history_score": "0.3000",
                    "final_score": "0.4200",
                }
            },
        )

    def test_stage8_fake_llm_updates_match_explanation_fields(self) -> None:
        class FakeExplanationClient:
            model = "fake-explainer"

            def explain(self, payload: dict) -> dict:
                self.payload = payload
                return {
                    "explanation": "The grant fits because it supports AI SMEs in Ukraine.",
                    "risks_text": "Verify eligible costs and deadline before prioritising.",
                    "manual_checks": ["verify eligible costs", "deadline missing"],
                    "llm_score": "0.7400",
                    "confidence": "0.8200",
                }

        match = self._seed_match()
        fake_client = FakeExplanationClient()

        summary = MatchExplanationService(repository=self.repository, client=fake_client).run(match_run_id=match.match_run_id, limit=5)
        refreshed = self.session.scalar(select(GrantClientMatch).where(GrantClientMatch.id == match.id))

        self.assertEqual(summary.job.status, "success")
        self.assertEqual(summary.processed_count, 1)
        self.assertEqual(summary.updated_count, 1)
        self.assertIn("AI SMEs", refreshed.explanation)
        self.assertIn("eligible costs", refreshed.risks_text)
        self.assertIn("verify eligible costs", refreshed.manual_checks)
        self.assertIn("deadline missing", refreshed.manual_checks)
        self.assertEqual(refreshed.llm_score, Decimal("0.7400"))
        self.assertEqual(refreshed.match_metadata["llm_explanation"]["provider_model"], "fake-explainer")
        self.assertEqual(fake_client.payload["grant_profile"]["title"], "AI innovation grant")
        self.assertEqual(fake_client.payload["client_profile"]["slug"], "ai-client")
        self.assertEqual(fake_client.payload["relevant_application_history"][0]["result"], "lost")

    def test_stage8_rule_provider_generates_offline_explanation(self) -> None:
        match = self._seed_match()

        summary = MatchExplanationService(repository=self.repository, provider="rule").run(match_run_id=match.match_run_id, limit=5)
        refreshed = self.session.scalar(select(GrantClientMatch).where(GrantClientMatch.id == match.id))

        self.assertEqual(summary.job.status, "success")
        self.assertIn("Candidate match because", refreshed.explanation)
        self.assertIn("semantic similarity", refreshed.explanation)
        self.assertEqual(refreshed.match_metadata["llm_explanation"]["provider_model"], "local-rule-explanation-v1")

    def test_stage8_uses_latest_match_run_when_id_is_not_provided(self) -> None:
        match = self._seed_match()

        summary = MatchExplanationService(repository=self.repository, provider="rule").run(limit=1)
        refreshed = self.session.scalar(select(GrantClientMatch).where(GrantClientMatch.id == match.id))

        self.assertEqual(summary.match_run_id, match.match_run_id)
        self.assertIsNotNone(refreshed.explanation)


if __name__ == "__main__":
    unittest.main()
