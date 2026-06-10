from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.db import Base
from grant_tool.db.models import AccessStrategy, DiscoveredGrantItem, JobStatus, JobType, Source
from grant_tool.db.repositories import GrantRepository
from grant_tool.ingestion.types import DetailFetchStatus, DiscoveredGrantItemDraft, DiscoveryStatus
from grant_tool.sources import seed_mvp_sources


class RepositoryTestCase(unittest.TestCase):
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

    def test_stage2_repository_smoke_flow(self) -> None:
        source = self.repository.upsert_source(
            slug="test-source",
            name="Test Source",
            base_url="https://example.com",
            access_strategy=AccessStrategy.API,
            api_url="https://example.com/api",
        )
        snapshot = self.repository.save_raw_snapshot(
            source_id=source.id,
            source_url="https://example.com/grants/1",
            source_record_id="grant-1",
            content_hash="a" * 64,
            raw_payload={"title": "AI innovation grant"},
        )
        duplicate_snapshot = self.repository.save_raw_snapshot(
            source_id=source.id,
            source_url="https://example.com/grants/1",
            source_record_id="grant-1",
            content_hash="a" * 64,
            raw_payload={"title": "AI innovation grant"},
        )
        grant = self.repository.upsert_grant(
            source_id=source.id,
            source_record_id="grant-1",
            source_url="https://example.com/grants/1",
            latest_raw_snapshot_id=snapshot.id,
            title="AI innovation grant",
            status="open",
            topics=["AI", "innovation"],
            countries=["Ukraine"],
        )
        client = self.repository.upsert_client_profile(
            slug="ukrainian-ai-company",
            name="Ukrainian AI Company",
            country="Ukraine",
            organization_type="company",
            technologies=["AI"],
            target_topics=["AI", "innovation"],
        )
        history = self.repository.save_application_history(
            client_profile_id=client.id,
            client_name=client.name,
            grant_title="Previous innovation grant",
            result="lost",
            topics=["AI"],
            reusable_materials="Concept note",
        )
        match_run = self.repository.create_match_run(name="Smoke match run")
        match = self.repository.save_match_result(
            match_run_id=match_run.id,
            grant_id=grant.id,
            client_profile_id=client.id,
            score=Decimal("0.8123"),
            keyword_score=Decimal("0.7000"),
            history_score=Decimal("0.2000"),
            explanation="Strong topic and country fit.",
        )
        self.assertEqual(source.access_strategy, "api")
        self.assertEqual(snapshot.id, duplicate_snapshot.id)
        self.assertEqual(grant.latest_raw_snapshot_id, snapshot.id)
        self.assertEqual(client.country, "Ukraine")
        self.assertEqual(history.result, "lost")
        self.assertEqual(match.score, Decimal("0.8123"))

    def test_stage1_discovered_item_upsert_tracks_known_items(self) -> None:
        source = self.repository.upsert_source(
            slug="test-source",
            name="Test Source",
            base_url="https://example.com",
            access_strategy=AccessStrategy.API,
            api_url="https://example.com/api",
        )
        draft = DiscoveredGrantItemDraft(
            source_url="https://example.com/grants/1?utm_source=test",
            canonical_url="https://example.com/grants/1",
            source_record_id="grant-1",
            title_hint="AI innovation grant",
            listing_url="https://example.com/api",
            listing_position=1,
            content_hash="b" * 64,
            discovery_metadata={"strategy": "api"},
        )

        first_item, first_created = self.repository.upsert_discovered_item(
            source_id=source.id,
            source_slug=source.slug,
            draft=draft,
        )
        second_item, second_created = self.repository.upsert_discovered_item(
            source_id=source.id,
            source_slug=source.slug,
            draft=draft,
        )
        self.repository.mark_discovered_detail_status(
            second_item,
            detail_fetch_status=DetailFetchStatus.SKIPPED_KNOWN,
            metadata={"last_skip_reason": "known_discovered_item"},
        )
        discovered_count = self.session.scalar(select(func.count(DiscoveredGrantItem.id)))

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_item.id, second_item.id)
        self.assertEqual(discovered_count, 1)
        self.assertEqual(second_item.discovery_status, DiscoveryStatus.KNOWN.value)
        self.assertEqual(second_item.detail_fetch_status, DetailFetchStatus.SKIPPED_KNOWN.value)
        self.assertEqual(second_item.discovery_metadata["last_skip_reason"], "known_discovered_item")

    def test_stage7_lists_known_items_due_for_refresh(self) -> None:
        source = self.repository.upsert_source(
            slug="test-source",
            name="Test Source",
            base_url="https://example.com",
            access_strategy=AccessStrategy.API,
            api_url="https://example.com/api",
        )
        due_draft = DiscoveredGrantItemDraft(
            source_url="https://example.com/grants/due",
            canonical_url="https://example.com/grants/due",
            source_record_id="due",
            title_hint="Due grant",
        )
        fresh_draft = DiscoveredGrantItemDraft(
            source_url="https://example.com/grants/fresh",
            canonical_url="https://example.com/grants/fresh",
            source_record_id="fresh",
            title_hint="Fresh grant",
        )
        due_item, _created = self.repository.upsert_discovered_item(
            source_id=source.id,
            source_slug=source.slug,
            draft=due_draft,
        )
        self.repository.upsert_discovered_item(
            source_id=source.id,
            source_slug=source.slug,
            draft=fresh_draft,
        )
        due_grant = self.repository.upsert_grant(
            source_id=source.id,
            source_record_id="due",
            source_url="https://example.com/grants/due",
            title="Due grant",
            status="open",
        )
        fresh_grant = self.repository.upsert_grant(
            source_id=source.id,
            source_record_id="fresh",
            source_url="https://example.com/grants/fresh",
            title="Fresh grant",
            status="open",
        )
        now = datetime.now(UTC)
        due_grant.updated_at = now - timedelta(days=15)
        fresh_grant.updated_at = now - timedelta(days=2)
        self.session.flush()

        due_items = self.repository.list_discovered_items_due_for_refresh(
            source_id=source.id,
            now=now,
            open_interval_days=7,
            no_deadline_interval_days=14,
        )

        self.assertEqual([item.id for item in due_items], [due_item.id])

    def test_stage8_search_source_report_counts_operational_state(self) -> None:
        source = self.repository.upsert_source(
            slug="test-source",
            name="Test Source",
            base_url="https://example.com",
            access_strategy=AccessStrategy.API,
            api_url="https://example.com/api",
        )
        first_item, _created = self.repository.upsert_discovered_item(
            source_id=source.id,
            source_slug=source.slug,
            draft=DiscoveredGrantItemDraft(
                source_url="https://example.com/grants/1",
                canonical_url="https://example.com/grants/1",
                source_record_id="grant-1",
                title_hint="Open AI grant",
            ),
        )
        second_item, _created = self.repository.upsert_discovered_item(
            source_id=source.id,
            source_slug=source.slug,
            draft=DiscoveredGrantItemDraft(
                source_url="https://example.com/grants/2",
                canonical_url="https://example.com/grants/2",
                source_record_id="grant-2",
                title_hint="Known grant",
            ),
        )
        self.repository.upsert_discovered_item(
            source_id=source.id,
            source_slug=source.slug,
            draft=DiscoveredGrantItemDraft(
                source_url="https://example.com/grants/2",
                canonical_url="https://example.com/grants/2",
                source_record_id="grant-2",
                title_hint="Known grant",
            ),
        )
        self.repository.mark_discovered_detail_status(first_item, detail_fetch_status=DetailFetchStatus.FETCHED)
        self.repository.mark_discovered_detail_status(second_item, detail_fetch_status=DetailFetchStatus.SKIPPED_KNOWN)
        self.repository.upsert_grant(
            source_id=source.id,
            source_record_id="grant-1",
            source_url="https://example.com/grants/1",
            title="Open AI grant",
            status="open",
        )
        self.repository.upsert_grant(
            source_id=source.id,
            source_record_id="grant-2",
            source_url="https://example.com/grants/2",
            title="Unknown grant",
            status="unknown",
            needs_manual_review=True,
        )
        job = self.repository.start_job(
            job_type=JobType.INGESTION,
            source_id=source.id,
            job_metadata={"refresh_due_count": 1, "refreshed_known_count": 1},
        )
        self.repository.increment_job_counters(job, processed=2, created=1, updated=1, skipped=1)
        self.repository.finish_job_success(job)

        rows = self.repository.search_source_report(source_slug="test-source")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.source_slug, "test-source")
        self.assertEqual(row.discovered_total, 2)
        self.assertEqual(row.discovery_new, 1)
        self.assertEqual(row.discovery_known, 1)
        self.assertEqual(row.detail_fetched, 1)
        self.assertEqual(row.detail_skipped_known, 1)
        self.assertEqual(row.grants_total, 2)
        self.assertEqual(row.grants_open, 1)
        self.assertEqual(row.grants_unknown, 1)
        self.assertEqual(row.grants_manual_review, 1)
        self.assertEqual(row.latest_job_status, JobStatus.SUCCESS.value)
        self.assertEqual(row.latest_job_processed, 2)
        self.assertEqual(row.latest_job_refresh_due, 1)
        self.assertEqual(row.latest_job_refreshed_known, 1)
        self.assertIsNotNone(row.last_seen_at)

    def test_stage9_quality_gate_counts_only_grant_like_records(self) -> None:
        source = self.repository.upsert_source(
            slug="prostir",
            name="Prostir",
            base_url="https://www.prostir.ua",
            access_strategy=AccessStrategy.RSS,
        )
        self.repository.upsert_grant(
            source_id=source.id,
            source_record_id="quality-1",
            source_url="https://www.prostir.ua/grant/quality-1",
            title="Грантова програма для українських МСП",
            status="open",
            deadline_text="до 31 грудня 2026",
            funding_amount_text="до 100000 грн",
            countries=["Ukraine"],
        )
        self.repository.upsert_grant(
            source_id=source.id,
            source_record_id="quality-2",
            source_url="https://www.prostir.ua/grant/quality-2",
            title="Call for applications: innovation grant",
            status="unknown",
            summary="Funding support for SMEs.",
            applicant_types=["SME"],
            needs_manual_review=True,
        )
        self.repository.upsert_grant(
            source_id=source.id,
            source_record_id="noise-1",
            source_url="https://www.prostir.ua/news/noise",
            title="News",
            status="unknown",
        )

        rows = self.repository.search_quality_gate_report(
            required_source_slugs=["prostir"],
            required_count=2,
            sample_limit=10,
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row.required)
        self.assertTrue(row.passed)
        self.assertEqual(row.grants_total, 3)
        self.assertEqual(row.quality_approved_count, 2)
        self.assertEqual(row.rejected_count, 1)
        self.assertCountEqual([sample.title for sample in row.samples], [
            "Call for applications: innovation grant",
            "Грантова програма для українських МСП",
        ])

    def test_stage9_quality_gate_treats_grantforward_as_structured_grant_search(self) -> None:
        source = self.repository.upsert_source(
            slug="grantforward",
            name="GrantForward",
            base_url="https://www.grantforward.com",
            access_strategy=AccessStrategy.API,
        )
        self.repository.upsert_grant(
            source_id=source.id,
            source_record_id="1198758",
            source_url="https://www.grantforward.com/grant?grant_id=1198758",
            title="The Canada Fund for Local Initiatives - Ukraine (2026)",
            status="open",
            deadline_text="June 10, 2026",
            funder_name="Government of Canada",
            needs_manual_review=True,
        )

        rows = self.repository.search_quality_gate_report(
            required_source_slugs=["grantforward"],
            required_count=1,
            sample_limit=10,
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].passed)
        self.assertEqual(rows[0].quality_approved_count, 1)

    def test_stage25_job_lifecycle(self) -> None:
        source = self.repository.upsert_source(
            slug="test-source",
            name="Test Source",
            base_url="https://example.com",
            access_strategy=AccessStrategy.HTML,
        )
        job = self.repository.start_job(
            job_type=JobType.INGESTION,
            source_id=source.id,
            job_metadata={"source_slug": source.slug},
        )
        self.repository.increment_job_counters(job, processed=3, created=1, updated=1, skipped=1)
        self.repository.finish_job_success(job, job_metadata={"done": True})

        self.assertEqual(job.job_type, "ingestion")
        self.assertEqual(job.status, JobStatus.SUCCESS.value)
        self.assertEqual(job.processed_count, 3)
        self.assertEqual(job.created_count, 1)
        self.assertEqual(job.updated_count, 1)
        self.assertEqual(job.skipped_count, 1)
        self.assertEqual(job.failed_count, 0)
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(job.job_metadata["source_slug"], "test-source")
        self.assertTrue(job.job_metadata["done"])

    def test_stage25_job_failure_and_partial_statuses(self) -> None:
        failed_job = self.repository.start_job(job_type=JobType.QUALITY_SCORE)
        self.repository.finish_job_failed(failed_job, error_message="template error")

        partial_job = self.repository.start_job(job_type=JobType.INGESTION)
        self.repository.increment_job_counters(partial_job, processed=5, created=4, failed=1)
        self.repository.mark_job_partial(
            partial_job,
            error_message="one detail page failed",
            job_metadata={"failed_urls": ["https://example.com/broken"]},
        )

        self.assertEqual(failed_job.status, JobStatus.FAILED.value)
        self.assertEqual(failed_job.error_message, "template error")
        self.assertEqual(partial_job.status, JobStatus.PARTIAL.value)
        self.assertEqual(partial_job.failed_count, 1)
        self.assertEqual(partial_job.job_metadata["failed_urls"], ["https://example.com/broken"])

    def test_stage25_seed_mvp_sources_is_idempotent(self) -> None:
        first_job, first_sources = seed_mvp_sources(self.repository)
        second_job, second_sources = seed_mvp_sources(self.repository)

        source_count = self.session.scalar(select(func.count(Source.id)))

        self.assertEqual(source_count, 12)
        self.assertEqual(len(first_sources), 12)
        self.assertEqual(len(second_sources), 12)
        self.assertEqual(first_job.created_count, 12)
        self.assertEqual(first_job.updated_count, 0)
        self.assertEqual(second_job.created_count, 0)
        self.assertEqual(second_job.updated_count, 12)
        self.assertEqual(first_job.status, JobStatus.SUCCESS.value)
        self.assertEqual(second_job.status, JobStatus.SUCCESS.value)
        self.assertIsNotNone(self.repository.get_source_by_slug("eu-funding"))
        self.assertEqual(self.repository.get_source_by_slug("prostir").access_strategy, "rss")
        self.assertEqual(self.repository.get_source_by_slug("chas-zmin").access_strategy, "wp_rest")
        self.assertEqual(self.repository.get_source_by_slug("eufundingportal-eu").access_strategy, "wp_rest")
        self.assertEqual(self.repository.get_source_by_slug("hromady").access_strategy, "wp_rest")
        self.assertEqual(self.repository.get_source_by_slug("nipo").access_strategy, "wp_rest")
        self.assertEqual(self.repository.get_source_by_slug("grant-market").access_strategy, "sitemap_html")
        self.assertEqual(self.repository.get_source_by_slug("fundsforngos").access_strategy, "wp_rest")
        self.assertEqual(self.repository.get_source_by_slug("opportunitydesk").access_strategy, "wp_rest")
        self.assertEqual(self.repository.get_source_by_slug("grantforward").access_strategy, "api")


if __name__ == "__main__":
    unittest.main()
