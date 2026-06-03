from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.data_quality import (
    ALLOWED_CLASSIFICATIONS,
    ALLOWED_STATUSES,
    CORE_FIELDS,
    DEFAULT_GRANT_QUALITY_CONTRACT,
    IMPORTANT_OPTIONAL_FIELDS,
    GrantClassification,
    GrantQualityTier,
    GrantStatus,
    ManualReviewRule,
    QualityFlag,
    SourceFamily,
    evaluate_grant_quality_contract,
)
from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy
from grant_tool.db.repositories import GrantRepository


class DataQualityContractTestCase(unittest.TestCase):
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

    def test_contract_exposes_allowed_values_and_field_groups(self) -> None:
        self.assertEqual(ALLOWED_STATUSES, {"open", "closed", "unknown"})
        self.assertIn(GrantStatus.OPEN.value, DEFAULT_GRANT_QUALITY_CONTRACT.allowed_statuses)
        self.assertIn(GrantClassification.GRANT.value, ALLOWED_CLASSIFICATIONS)
        self.assertIn(GrantClassification.WEBINAR.value, ALLOWED_CLASSIFICATIONS)
        self.assertIn("title", CORE_FIELDS)
        self.assertIn("source_url", CORE_FIELDS)
        self.assertIn("deadline_at", IMPORTANT_OPTIONAL_FIELDS)
        self.assertIn("application_url", IMPORTANT_OPTIONAL_FIELDS)

    def test_match_ready_record_has_no_contract_warnings(self) -> None:
        source = self.repository.upsert_source(
            slug="diia-business",
            name="Diia Business",
            base_url="https://www.business.diia.gov.ua",
            access_strategy=AccessStrategy.SITEMAP_HTML,
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://www.business.diia.gov.ua/finance/grant",
            application_url="https://apply.example.org",
            title="Grant for Ukrainian technology SMEs",
            summary="Funding for Ukrainian companies building technology products.",
            status="open",
            published_at=datetime(2026, 1, 10, tzinfo=UTC),
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            deadline_text="31 December 2026",
            funder_name="Diia Business",
            funding_amount_text="up to 100000 UAH",
            currency="UAH",
            countries=["Ukraine"],
            regions=["Kyiv"],
            eligibility_text="Eligible applicants are Ukrainian SMEs.",
            opportunity_type="grant",
            support_type="grant",
            applicant_types=["SME"],
            topics=["technology"],
            extraction_confidence=Decimal("0.9000"),
        )

        evaluation = evaluate_grant_quality_contract(grant)

        self.assertEqual(evaluation.tier, GrantQualityTier.MATCH_READY)
        self.assertEqual(evaluation.classification, GrantClassification.GRANT)
        self.assertEqual(evaluation.source_family, SourceFamily.STRUCTURED_DIRECT)
        self.assertTrue(evaluation.core_complete)
        self.assertTrue(evaluation.matching_eligible)
        self.assertEqual(evaluation.flags, ())
        self.assertEqual(evaluation.important_missing_fields, ())

    def test_missing_optional_fields_create_warnings_without_auto_reject(self) -> None:
        source = self.repository.upsert_source(
            slug="prostir",
            name="Prostir",
            base_url="https://www.prostir.ua",
            access_strategy=AccessStrategy.RSS,
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://www.prostir.ua/grants/ai-support",
            title="Open call for AI support for Ukrainian SMEs",
            summary="Funding support for SMEs developing AI products in Ukraine.",
            status="unknown",
            countries=["Ukraine"],
            topics=["AI"],
            applicant_types=["SME"],
            opportunity_type="grant",
        )

        evaluation = evaluate_grant_quality_contract(grant)

        self.assertEqual(evaluation.tier, GrantQualityTier.USABLE_WITH_WARNINGS)
        self.assertEqual(evaluation.source_family, SourceFamily.USEFUL_INCOMPLETE)
        self.assertTrue(evaluation.core_complete)
        self.assertTrue(evaluation.matching_eligible)
        self.assertIn(QualityFlag.STATUS_UNKNOWN, evaluation.flags)
        self.assertIn(QualityFlag.MISSING_DEADLINE, evaluation.flags)
        self.assertIn(QualityFlag.MISSING_FUNDER, evaluation.flags)
        self.assertIn(QualityFlag.MISSING_REGION, evaluation.flags)
        self.assertIn(QualityFlag.MISSING_APPLICATION_URL, evaluation.flags)
        self.assertIn(QualityFlag.MISSING_PUBLISHED_AT, evaluation.flags)
        self.assertNotIn(QualityFlag.NEEDS_MANUAL_REVIEW, evaluation.flags)

    def test_manual_review_or_low_confidence_blocks_matching(self) -> None:
        source = self.repository.upsert_source(
            slug="grant-market",
            name="Grant Market",
            base_url="https://grant.market",
            access_strategy=AccessStrategy.SITEMAP_HTML,
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://grant.market/opp/weak",
            title="Grant for recovery projects",
            summary="Funding for recovery projects in Ukraine.",
            status="open",
            countries=["Ukraine"],
            opportunity_type="grant",
            needs_manual_review=True,
            manual_review_reason="Needs source verification.",
            extraction_confidence=Decimal("0.4000"),
        )

        evaluation = evaluate_grant_quality_contract(grant)

        self.assertEqual(evaluation.tier, GrantQualityTier.NEEDS_REVIEW)
        self.assertFalse(evaluation.matching_eligible)
        self.assertIn(QualityFlag.NEEDS_MANUAL_REVIEW, evaluation.flags)
        self.assertIn(QualityFlag.LOW_EXTRACTION_CONFIDENCE, evaluation.flags)
        self.assertIn(ManualReviewRule.EXPLICIT_MANUAL_REVIEW, evaluation.manual_review_rules)
        self.assertIn(ManualReviewRule.LOW_EXTRACTION_CONFIDENCE, evaluation.manual_review_rules)

    def test_explicit_non_grant_classification_is_noise_rejected(self) -> None:
        source = self.repository.upsert_source(
            slug="nipo",
            name="NIPO",
            base_url="https://nipo.gov.ua",
            access_strategy=AccessStrategy.WP_REST,
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://nipo.gov.ua/training",
            title="Training course for startup teams",
            summary="Training course for teams interested in innovation.",
            status="open",
            countries=["Ukraine"],
            opportunity_type="training",
            support_type="training",
        )

        evaluation = evaluate_grant_quality_contract(grant)

        self.assertEqual(evaluation.tier, GrantQualityTier.NOISE_REJECTED)
        self.assertEqual(evaluation.classification, GrantClassification.TRAINING)
        self.assertEqual(evaluation.source_family, SourceFamily.DIGEST_HEAVY)
        self.assertFalse(evaluation.matching_eligible)
        self.assertIn(QualityFlag.POSSIBLE_TRAINING, evaluation.flags)
        self.assertIn(QualityFlag.NOISE_REJECTED, evaluation.flags)
        self.assertIn(ManualReviewRule.NOISE_OR_NON_GRANT, evaluation.manual_review_rules)

    def test_deterministic_text_classifies_digest_webinar_event_news_and_article_noise(self) -> None:
        source = self.repository.upsert_source(
            slug="hromady",
            name="Hromady",
            base_url="https://hromady.org",
            access_strategy=AccessStrategy.WP_REST,
        )
        cases = [
            ("digest", "Грантовий гід: добірка конкурсів та грантових можливостей", GrantClassification.DIGEST),
            ("webinar", "Кроки розвитку громад розглянемо під час вебінару", GrantClassification.WEBINAR),
            ("event", "Варшава - ReBuild Ukraine: Construction & Energy conference", GrantClassification.EVENT),
            ("news", "IP офіс зареєстрував авторське право на комп’ютерну програму", GrantClassification.NEWS),
            ("article", "Як підготувати заявку: поради для стартапів", GrantClassification.ARTICLE),
        ]

        for record_id, title, expected_classification in cases:
            with self.subTest(record_id=record_id):
                grant = self.repository.upsert_grant(
                    source_id=source.id,
                    source_record_id=record_id,
                    source_url=f"https://hromady.org/{record_id}",
                    title=title,
                    summary="Informational post for communities.",
                    status="unknown",
                    countries=["Ukraine"],
                )

                evaluation = evaluate_grant_quality_contract(grant)

                self.assertEqual(evaluation.classification, expected_classification)
                self.assertEqual(evaluation.tier, GrantQualityTier.NOISE_REJECTED)
                self.assertFalse(evaluation.matching_eligible)
                self.assertIn(QualityFlag.NOISE_REJECTED, evaluation.flags)
                self.assertTrue(evaluation.classification_reasons)

    def test_direct_grant_language_wins_over_generic_source_noise_risk(self) -> None:
        source = self.repository.upsert_source(
            slug="prostir",
            name="Prostir",
            base_url="https://www.prostir.ua",
            access_strategy=AccessStrategy.RSS,
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://www.prostir.ua/grants/direct-call",
            title="Конкурс грантів для підтримки ГО в реалізації проектів",
            summary="Оголошено прийом заявок на фінансування проектів громадських організацій.",
            status="open",
            deadline_text="до 31 грудня 2026",
            funding_amount_text="до 20000 GBP",
            countries=["Ukraine"],
            opportunity_type=None,
            support_type=None,
        )

        evaluation = evaluate_grant_quality_contract(grant)

        self.assertEqual(evaluation.classification, GrantClassification.GRANT)
        self.assertNotEqual(evaluation.tier, GrantQualityTier.NOISE_REJECTED)
        self.assertTrue(evaluation.matching_eligible)
        self.assertIn("text:direct_grant_signal", evaluation.classification_reasons)

    def test_digest_heavy_unknown_records_need_review_before_matching(self) -> None:
        source = self.repository.upsert_source(
            slug="nipo",
            name="NIPO",
            base_url="https://nipo.gov.ua",
            access_strategy=AccessStrategy.WP_REST,
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://nipo.gov.ua/ambiguous",
            title="IP Management Clinics вперше в Україні",
            summary="Програма підтримки компаній із консультаціями щодо інтелектуальної власності.",
            status="unknown",
            countries=["Ukraine"],
        )

        evaluation = evaluate_grant_quality_contract(grant)

        self.assertEqual(evaluation.classification, GrantClassification.UNKNOWN)
        self.assertEqual(evaluation.tier, GrantQualityTier.NEEDS_REVIEW)
        self.assertFalse(evaluation.matching_eligible)
        self.assertIn(QualityFlag.SOURCE_CLASSIFICATION_UNCERTAIN, evaluation.flags)
        self.assertIn(ManualReviewRule.SOURCE_CLASSIFICATION_UNCERTAIN, evaluation.manual_review_rules)

    def test_closed_records_are_usable_but_not_active_matching_candidates(self) -> None:
        source = self.repository.upsert_source(
            slug="eu-funding",
            name="EU Funding",
            base_url="https://ec.europa.eu",
            access_strategy=AccessStrategy.API,
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://ec.europa.eu/info/funding/example",
            title="Closed Horizon grant for Ukrainian SMEs",
            summary="A structured grant record that is now closed.",
            status="closed",
            deadline_at=datetime(2026, 1, 1, tzinfo=UTC),
            funder_name="European Commission",
            countries=["Ukraine"],
            regions=["EU"],
            eligibility_text="Eligible applicants include SMEs.",
            opportunity_type="grant",
        )

        evaluation = evaluate_grant_quality_contract(grant)

        self.assertEqual(evaluation.tier, GrantQualityTier.USABLE_WITH_WARNINGS)
        self.assertFalse(evaluation.matching_eligible)
        self.assertIn(QualityFlag.CLOSED_STATUS, evaluation.flags)
        self.assertIn(QualityFlag.CLOSED_STATUS.value, evaluation.matching_blockers)

    def test_source_family_contract_matches_audit_strategy(self) -> None:
        self.assertEqual(DEFAULT_GRANT_QUALITY_CONTRACT.source_family_by_slug["nipo"], SourceFamily.DIGEST_HEAVY)
        self.assertEqual(DEFAULT_GRANT_QUALITY_CONTRACT.source_family_by_slug["hromady"], SourceFamily.DIGEST_HEAVY)
        self.assertEqual(DEFAULT_GRANT_QUALITY_CONTRACT.source_family_by_slug["eufundingportal-eu"], SourceFamily.AGGREGATOR)
        self.assertEqual(DEFAULT_GRANT_QUALITY_CONTRACT.source_family_by_slug["gurt"], SourceFamily.EMPTY_OR_PROBLEM)


if __name__ == "__main__":
    unittest.main()
