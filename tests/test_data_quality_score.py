from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.data_quality import (
    DEFAULT_MIN_MATCHING_QUALITY_SCORE,
    GrantQualityTier,
    QUALITY_SCORING_VERSION,
    apply_grant_quality_score,
    compute_grant_quality_score,
)
from grant_tool.data_quality.service import QualityScoringService
from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, JobType
from grant_tool.db.repositories import GrantRepository
from grant_tool.matching import ShortlistMatchingService


class DataQualityScoreTestCase(unittest.TestCase):
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
            slug="eu-funding",
            name="EU Funding",
            base_url="https://ec.europa.eu",
            access_strategy=AccessStrategy.API,
        )
        self.noisy_source = self.repository.upsert_source(
            slug="nipo",
            name="NIPO",
            base_url="https://nipo.example",
            access_strategy=AccessStrategy.WP_REST,
        )

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _rich_grant(self, **overrides):
        fields = {
            "source_id": self.source.id,
            "source_url": "https://ec.europa.eu/grants/ai-call",
            "title": "AI innovation grant for Ukrainian SMEs",
            "status": "open",
            "summary": "Funding for Ukrainian SMEs building AI products with clear eligibility rules and application guidance.",
            "description_text": (
                "Eligible applicants are Ukrainian SME companies and startups. The grant funds artificial intelligence "
                "innovation projects in Ukraine, with documented implementation plans, application requirements, "
                "evaluation criteria, and reporting obligations described in detail on the call page."
            ),
            "application_url": "https://ec.europa.eu/grants/ai-call/apply",
            "published_at": datetime.now(UTC) - timedelta(days=3),
            "deadline_at": datetime.now(UTC) + timedelta(days=90),
            "deadline_text": "Deadline: in 90 days",
            "funder_name": "European Commission",
            "program_name": "Horizon Europe",
            "funding_amount_text": "EUR 100 000",
            "currency": "EUR",
            "countries": ["Ukraine", "EU"],
            "regions": ["Kyiv"],
            "eligibility_text": "Eligible applicants are Ukrainian SME companies.",
            "applicant_types": ["SME"],
            "topics": ["AI", "innovation"],
            "keywords": ["AI"],
        }
        fields.update(overrides)
        return self.repository.upsert_grant(**fields)

    def test_rich_grant_scores_high_and_is_matching_ready(self) -> None:
        grant = self._rich_grant()

        result = compute_grant_quality_score(grant)

        self.assertEqual(result.tier, GrantQualityTier.MATCH_READY)
        self.assertGreaterEqual(result.score, 80)
        self.assertLessEqual(result.score, 100)
        self.assertTrue(result.matching_ready)
        self.assertEqual(result.penalties, {})

    def test_score_is_deterministic(self) -> None:
        grant = self._rich_grant()

        first = compute_grant_quality_score(grant)
        second = compute_grant_quality_score(grant)

        self.assertEqual(first.score, second.score)
        self.assertEqual(first.components, second.components)
        self.assertEqual(first.flags, second.flags)

    def test_noise_record_scores_low_with_explainable_penalty(self) -> None:
        grant = self.repository.upsert_grant(
            source_id=self.noisy_source.id,
            source_url="https://nipo.example/webinar-grant-writing",
            title="Вебінар: як писати заявки",
            status="unknown",
            summary="Запрошуємо на вебінар про підготовку заявок для організацій.",
        )

        result = compute_grant_quality_score(grant)

        self.assertEqual(result.tier, GrantQualityTier.NOISE_REJECTED)
        self.assertIn("penalty_noise_classification", result.penalties)
        self.assertLess(result.score, DEFAULT_MIN_MATCHING_QUALITY_SCORE)
        self.assertFalse(result.matching_ready)

    def test_apply_persists_columns_and_explainable_metadata(self) -> None:
        grant = self._rich_grant()

        result = apply_grant_quality_score(grant)
        self.session.flush()

        self.assertEqual(grant.quality_score, result.score)
        self.assertEqual(grant.quality_tier, result.tier.value)
        self.assertEqual(grant.quality_flags, [flag.value for flag in result.flags])
        quality_metadata = grant.extraction_metadata["quality"]
        self.assertEqual(quality_metadata["version"], QUALITY_SCORING_VERSION)
        self.assertEqual(quality_metadata["score"], result.score)
        self.assertIn("components", quality_metadata)
        self.assertIn("penalties", quality_metadata)

    def test_quality_scoring_service_persists_and_reports(self) -> None:
        self._rich_grant()
        self.repository.upsert_grant(
            source_id=self.noisy_source.id,
            source_url="https://nipo.example/webinar-grant-writing",
            title="Вебінар: як писати заявки",
            status="unknown",
            summary="Запрошуємо на вебінар про підготовку заявок для організацій.",
        )

        summary = QualityScoringService(repository=self.repository).run()

        self.assertEqual(summary.processed_count, 2)
        self.assertFalse(summary.dry_run)
        self.assertEqual(summary.job.job_type, JobType.QUALITY_SCORE.value)
        self.assertEqual(sum(summary.tier_counts.values()), 2)
        self.assertEqual(summary.tier_counts.get("noise_rejected"), 1)
        scored = self.repository.list_grants_for_quality_scoring()
        self.assertTrue(all(grant.quality_score is not None for grant in scored))

    def test_quality_scoring_service_dry_run_does_not_persist(self) -> None:
        grant = self._rich_grant()

        summary = QualityScoringService(repository=self.repository).run(dry_run=True)

        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.processed_count, 1)
        self.assertIsNone(grant.quality_score)
        self.assertIsNone(grant.quality_tier)

    def test_matching_blocks_low_persisted_score_without_explicit_permission(self) -> None:
        grant = self._rich_grant()
        grant.quality_score = DEFAULT_MIN_MATCHING_QUALITY_SCORE - 10
        grant.quality_tier = GrantQualityTier.USABLE_WITH_WARNINGS.value
        self.session.flush()
        client = self.repository.upsert_client_profile(
            slug="ai-client",
            name="AI Client",
            country="Ukraine",
            organization_type="SME company",
            technologies=["AI"],
            target_topics=["AI"],
        )

        service = ShortlistMatchingService(repository=self.repository)
        blocked = service.score(grant=grant, client=client)
        allowed = service.score(grant=grant, client=client, include_low_quality=True)

        low_score_reason = f"quality_gate:low_quality_score:{grant.quality_score}"
        self.assertFalse(blocked.hard_filter_passed)
        self.assertIn(low_score_reason, blocked.filter_reasons)
        self.assertNotIn(low_score_reason, allowed.filter_reasons)

    def test_prepared_grants_layer_excludes_noise_and_keeps_unscored(self) -> None:
        prepared = self._rich_grant()
        apply_grant_quality_score(prepared)
        noise = self.repository.upsert_grant(
            source_id=self.noisy_source.id,
            source_url="https://nipo.example/webinar-grant-writing",
            title="Вебінар: як писати заявки",
            status="unknown",
            summary="Запрошуємо на вебінар про підготовку заявок для організацій.",
        )
        apply_grant_quality_score(noise)
        unscored = self.repository.upsert_grant(
            source_id=self.source.id,
            source_url="https://ec.europa.eu/grants/unscored-call",
            title="Unscored direct grant call",
            status="open",
        )
        self.session.flush()

        prepared_set = self.repository.list_prepared_grants()
        prepared_ids = {grant.id for grant in prepared_set}

        self.assertIn(prepared.id, prepared_ids)
        self.assertIn(unscored.id, prepared_ids)
        self.assertNotIn(noise.id, prepared_ids)

        strict_set = self.repository.list_prepared_grants(include_unscored=False, min_quality_score=DEFAULT_MIN_MATCHING_QUALITY_SCORE)
        strict_ids = {grant.id for grant in strict_set}
        self.assertIn(prepared.id, strict_ids)
        self.assertNotIn(unscored.id, strict_ids)


if __name__ == "__main__":
    unittest.main()
