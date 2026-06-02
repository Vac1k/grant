from __future__ import annotations

import unittest
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.cli import _format_data_audit_report
from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy
from grant_tool.db.repositories import GrantRepository


class DataPreparationAuditTestCase(unittest.TestCase):
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

    def test_data_audit_reports_completeness_weak_records_and_noise(self) -> None:
        source = self.repository.upsert_source(
            slug="prostir",
            name="Prostir",
            base_url="https://www.prostir.ua",
            access_strategy=AccessStrategy.RSS,
        )
        self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://www.prostir.ua/grant/quality",
            application_url="https://apply.example.org",
            title="Грантова програма для українських МСП",
            summary="Підтримка українських малих і середніх підприємств.",
            status="open",
            published_at=datetime(2026, 1, 10, tzinfo=UTC),
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            deadline_text="до 31 грудня 2026",
            funder_name="Test Funder",
            funding_amount_text="до 100 000 грн",
            currency="UAH",
            countries=["Ukraine"],
            regions=["Kyiv"],
            eligibility_text="Податися можуть українські МСП.",
        )
        self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://www.prostir.ua/news/webinar",
            title="Вебінар про гранти для громад",
            summary="Запрошуємо на вебінар про можливості фінансування.",
            status="unknown",
            needs_manual_review=True,
            manual_review_reason="Looks like event content, not a direct grant.",
        )

        rows = self.repository.data_audit_report(source_slug="prostir", sample_limit=10)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.source_slug, "prostir")
        self.assertEqual(row.grants_total, 2)
        self.assertEqual(row.status_counts["open"], 1)
        self.assertEqual(row.status_counts["unknown"], 1)
        self.assertEqual(row.manual_review_count, 1)
        self.assertEqual(row.weak_record_count, 1)
        self.assertEqual(row.noise_candidate_count, 1)
        deadline = next(field for field in row.field_completeness if field.field_name == "deadline_at")
        self.assertEqual(deadline.populated_count, 1)
        self.assertEqual(deadline.missing_count, 1)
        self.assertIn("missing_deadline", row.weak_samples[0].reasons)
        self.assertIn("needs_manual_review", row.weak_samples[0].reasons)
        self.assertIn("possible_webinar", row.noise_samples[0].reasons)

    def test_data_audit_cli_formatter_includes_core_sections(self) -> None:
        source = self.repository.upsert_source(
            slug="nipo",
            name="NIPO",
            base_url="https://nipo.gov.ua",
            access_strategy=AccessStrategy.WP_REST,
        )
        self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://nipo.gov.ua/digest",
            title="Дайджест грантових можливостей",
            summary="Добірка можливостей для бізнесу.",
            status="unknown",
            needs_manual_review=True,
        )

        output = "\n".join(_format_data_audit_report(self.repository.data_audit_report()))

        self.assertIn("Grant data audit", output)
        self.assertIn("source: nipo", output)
        self.assertIn("manual review: 1/1 (100.0%)", output)
        self.assertIn("weakest fields:", output)
        self.assertIn("noise samples:", output)
        self.assertIn("possible_digest", output)


if __name__ == "__main__":
    unittest.main()
