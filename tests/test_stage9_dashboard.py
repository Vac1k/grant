from __future__ import annotations

import unittest
from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.dashboard.service import DashboardService
from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy
from grant_tool.db.session import get_session
from grant_tool.db.repositories import GrantRepository
from grant_tool.main import create_app


class Stage9DashboardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.session: Session = self.session_factory()
        self.repository = GrantRepository(self.session)
        self._seed_dashboard_data()
        self.session.commit()

        def override_session() -> Generator[Session, None, None]:
            with self.session_factory() as session:
                yield session

        self.app = create_app()
        self.app.dependency_overrides[get_session] = override_session
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    def _seed_dashboard_data(self) -> None:
        source = self.repository.upsert_source(
            slug="test-source",
            name="Test Source",
            base_url="https://example.org",
            access_strategy=AccessStrategy.API,
        )
        client = self.repository.upsert_client_profile(
            slug="ai-client",
            name="AI Client",
            country="Ukraine",
            sector="AI automation",
            organization_type="SME company",
            technologies=["AI", "machine learning"],
            target_topics=["AI", "innovation"],
            product_description="AI customer support automation product.",
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_url="https://example.org/ai-grant",
            title="AI innovation grant",
            status="open",
            deadline_at=datetime(2026, 12, 31, tzinfo=UTC),
            summary="Funding for AI products developed by Ukrainian SMEs.",
            countries=["Ukraine"],
            applicant_types=["SME"],
            topics=["AI", "innovation"],
            funding_amount_text="up to 500000",
            currency="EUR",
            extraction_confidence=Decimal("0.9000"),
        )
        self.repository.save_application_history(
            client_profile_id=client.id,
            client_name=client.name,
            grant_title="Previous AI grant",
            result="lost",
            topics=["AI"],
            reusable_materials="Concept note",
        )
        match_run = self.repository.create_match_run(name="Dashboard match run", status="success")
        self.repository.save_match_result(
            match_run_id=match_run.id,
            grant_id=grant.id,
            client_profile_id=client.id,
            score=Decimal("0.6400"),
            rank=1,
            keyword_score=Decimal("0.5000"),
            vector_score=Decimal("0.7000"),
            history_score=Decimal("0.3000"),
            llm_score=Decimal("0.8000"),
            explanation="Strong AI and SME fit.",
            risks_text="Verify eligible costs.",
            manual_checks=["verify deadline"],
        )

    def test_stage9_dashboard_service_builds_stats(self) -> None:
        stats = DashboardService(self.session).stats()

        self.assertEqual(stats.grants_total, 1)
        self.assertEqual(stats.grants_open, 1)
        self.assertEqual(stats.clients_total, 1)
        self.assertEqual(stats.matches_total, 1)
        self.assertEqual(stats.explained_matches, 1)
        self.assertEqual(stats.grants_unscored, 1)
        self.assertEqual(stats.grants_prepared, 0)
        self.assertEqual(stats.quality_tier_counts, {})

    def test_stage9_grants_quality_filter_separates_unscored_records(self) -> None:
        unscored = self.client.get("/grants?quality=unscored")
        prepared = self.client.get("/grants?quality=prepared")

        self.assertEqual(unscored.status_code, 200)
        self.assertIn("AI innovation grant", unscored.text)
        self.assertEqual(prepared.status_code, 200)
        self.assertNotIn("AI innovation grant", prepared.text)

    def test_stage9_dashboard_pages_render_core_data(self) -> None:
        paths = ["/", "/grants", "/clients", "/matches", "/report"]

        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("AI Grant Matching Tool", response.text)

        self.assertIn("AI innovation grant", self.client.get("/grants").text)
        self.assertIn("AI Client", self.client.get("/clients").text)
        self.assertIn("Strong AI and SME fit", self.client.get("/matches").text)
        self.assertIn("Top matches by client", self.client.get("/report").text)

    def test_stage9_grants_filters_are_rendered(self) -> None:
        response = self.client.get("/grants?source=test-source&status=open&topic=AI")

        self.assertEqual(response.status_code, 200)
        self.assertIn("AI innovation grant", response.text)
        self.assertIn("selected", response.text)


if __name__ == "__main__":
    unittest.main()
