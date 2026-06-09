from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from grant_tool.cli import _format_deduplication_summary, _format_quality_gate_report, _format_search_report
from grant_tool.db.repositories import SearchQualityGateRow, SearchQualityGrantSample, SearchSourceReportRow
from grant_tool.deduplication import DeduplicationSummary, DuplicateCandidate, DuplicateGroup


class Stage8SearchReportTestCase(unittest.TestCase):
    def test_stage8_cli_search_report_format_includes_operational_counters(self) -> None:
        rows = [
            SearchSourceReportRow(
                source_slug="prostir",
                enabled=True,
                discovered_total=12,
                discovery_new=2,
                discovery_known=10,
                discovery_failed=0,
                detail_not_fetched=0,
                detail_fetched=9,
                detail_failed=1,
                detail_skipped_known=2,
                grants_total=9,
                grants_open=6,
                grants_unknown=2,
                grants_manual_review=1,
                last_seen_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
                latest_job_status="success",
                latest_job_processed=12,
                latest_job_created=2,
                latest_job_updated=1,
                latest_job_skipped=9,
                latest_job_failed=0,
                latest_job_refresh_due=1,
                latest_job_refreshed_known=1,
            )
        ]

        output = "\n".join(_format_search_report(rows))

        self.assertIn("Search source report", output)
        self.assertIn("source | enabled | discovered | grants", output)
        self.assertIn("prostir | yes | 12 | 9 | 2/10 | 9/2/1", output)
        self.assertIn("open/unknown/manual", output)
        self.assertIn("success p=12 c=2 u=1 s=9 f=0", output)
        self.assertIn("1/1", output)
        self.assertIn("2026-05-24T12:00:00+00:00", output)

    def test_stage8_cli_search_report_handles_empty_sources(self) -> None:
        self.assertEqual(_format_search_report([]), ["No sources found"])

    def test_stage9_cli_quality_gate_report_marks_blocked_sources(self) -> None:
        rows = [
            SearchQualityGateRow(
                source_slug="prostir",
                required=True,
                required_count=10,
                grants_total=12,
                quality_approved_count=10,
                rejected_count=2,
                passed=True,
                samples=[
                    SearchQualityGrantSample(
                        title="Грантова програма для МСП",
                        status="open",
                        deadline_text="до 31 грудня 2026",
                        funding_amount_text="100000 грн",
                        source_url="https://www.prostir.ua/grant/1",
                        needs_manual_review=False,
                    )
                ],
            ),
            SearchQualityGateRow(
                source_slug="hromady",
                required=True,
                required_count=10,
                grants_total=6,
                quality_approved_count=5,
                rejected_count=1,
                passed=False,
                samples=[],
            ),
            SearchQualityGateRow(
                source_slug="gurt",
                required=False,
                required_count=10,
                grants_total=0,
                quality_approved_count=0,
                rejected_count=0,
                passed=True,
                samples=[],
            ),
        ]

        output = "\n".join(_format_quality_gate_report(rows))

        self.assertIn("Search quality gate: blocked (1/2 required sources passed)", output)
        self.assertIn("prostir | yes | 10/10 | 12 | 2 | passed", output)
        self.assertIn("hromady | yes | 5/10 | 6 | 1 | blocked", output)
        self.assertIn("gurt | no | 0/10 | 0 | 0 | excluded", output)
        self.assertIn("Грантова програма для МСП", output)

    def test_step5_cli_deduplication_summary_shows_groups_and_candidates(self) -> None:
        candidate = DuplicateCandidate(
            left_grant_id="grant-a",
            right_grant_id="grant-b",
            score=Decimal("0.9200"),
            reasons=("exact_normalized_title", "same_deadline"),
            duplicate=True,
        )
        summary = DeduplicationSummary(
            processed_count=2,
            candidate_count=1,
            duplicate_pair_count=1,
            duplicate_group_count=1,
            duplicate_record_count=1,
            candidates=(candidate,),
            groups=(
                DuplicateGroup(
                    group_id="dup-test",
                    primary_grant_id="grant-a",
                    grant_ids=("grant-a", "grant-b"),
                    candidates=(candidate,),
                ),
            ),
        )

        output = "\n".join(_format_deduplication_summary(summary))

        self.assertIn("Deduplication: processed=2 candidates=1 duplicate_pairs=1", output)
        self.assertIn("duplicate groups:", output)
        self.assertIn("dup-test: primary=grant-a size=2 best_score=0.9200", output)
        self.assertIn("top candidates:", output)
        self.assertIn("grant-a <> grant-b: exact_normalized_title, same_deadline", output)


if __name__ == "__main__":
    unittest.main()
