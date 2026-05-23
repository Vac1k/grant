from __future__ import annotations

import unittest
from datetime import UTC, datetime

from grant_tool.cli import _format_search_report
from grant_tool.db.repositories import SearchSourceReportRow


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


if __name__ == "__main__":
    unittest.main()
