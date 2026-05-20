from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from grant_tool.client_import import (
    import_application_history,
    import_client_profiles,
    slugify,
    split_list,
)
from grant_tool.db import Base
from grant_tool.db.models import ApplicationHistory, ClientProfile, JobRun, JobStatus, JobType
from grant_tool.db.repositories import GrantRepository


ROOT_DIR = Path(__file__).resolve().parents[1]
CLIENTS_FILE = ROOT_DIR / "data/manual_seed/client_profiles.manual.csv"
HISTORY_FILE = ROOT_DIR / "data/manual_seed/application_history.manual.csv"


class Stage4ImportTestCase(unittest.TestCase):
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

    def test_helpers_parse_manual_seed_fields(self) -> None:
        self.assertEqual(slugify("Vignette ID"), "vignette-id")
        self.assertEqual(split_list("AI; Voice AI; HPC"), ["AI", "Voice AI", "HPC"])
        self.assertEqual(split_list("a|b|c", separator="|"), ["a", "b", "c"])

    def test_import_manual_seed_is_idempotent(self) -> None:
        first_clients = import_client_profiles(self.repository, CLIENTS_FILE)
        first_history = import_application_history(self.repository, HISTORY_FILE)
        second_clients = import_client_profiles(self.repository, CLIENTS_FILE)
        second_history = import_application_history(self.repository, HISTORY_FILE)

        client_count = self.session.scalar(select(func.count(ClientProfile.id)))
        history_count = self.session.scalar(select(func.count(ApplicationHistory.id)))
        intelswift = self.repository.get_client_profile_by_slug("intelswift")
        vignette_history = self.session.scalar(
            select(ApplicationHistory).where(ApplicationHistory.client_name == "Vignette ID")
        )

        self.assertEqual(first_clients.created, 5)
        self.assertEqual(first_clients.failed, 0)
        self.assertEqual(first_history.created, 12)
        self.assertEqual(first_history.failed, 0)
        self.assertEqual(second_clients.created, 0)
        self.assertEqual(second_clients.updated, 5)
        self.assertEqual(second_history.created, 0)
        self.assertEqual(second_history.updated, 12)
        self.assertEqual(client_count, 5)
        self.assertEqual(history_count, 12)
        self.assertIsNotNone(intelswift)
        self.assertIn("Voice AI agents", intelswift.technologies)
        self.assertEqual(intelswift.profile_metadata["confidence"], "high")
        self.assertIsNotNone(vignette_history)
        self.assertTrue(vignette_history.history_metadata["manual_seed"])
        self.assertIn("source_documents", vignette_history.history_metadata)

    def test_import_jobs_are_recorded(self) -> None:
        import_client_profiles(self.repository, CLIENTS_FILE)
        import_application_history(self.repository, HISTORY_FILE)

        jobs = list(self.session.scalars(select(JobRun).order_by(JobRun.started_at)))

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].job_type, JobType.IMPORT_CLIENTS.value)
        self.assertEqual(jobs[0].status, JobStatus.SUCCESS.value)
        self.assertEqual(jobs[0].processed_count, 5)
        self.assertEqual(jobs[1].job_type, JobType.IMPORT_HISTORY.value)
        self.assertEqual(jobs[1].status, JobStatus.SUCCESS.value)
        self.assertEqual(jobs[1].processed_count, 12)

    def test_application_history_rejects_invalid_result(self) -> None:
        import_client_profiles(self.repository, CLIENTS_FILE)
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_file = Path(temp_dir) / "history.csv"
            invalid_file.write_text(
                "\n".join(
                    [
                        "client_name,grant_title,grant_source,program_name,application_date,result,country,applicant_type,topics,project_summary,reusable_materials,similarity_weight,notes,source_documents,confidence",
                        "Intelswift,Invalid Grant,Source,Program,,maybe,EU,SME,AI,Summary,Materials,1.0,Notes,doc.docx,low",
                    ]
                ),
                encoding="utf-8",
            )

            result = import_application_history(self.repository, invalid_file)

        history_count = self.session.scalar(select(func.count(ApplicationHistory.id)))

        self.assertEqual(result.failed, 1)
        self.assertEqual(result.created, 0)
        self.assertEqual(history_count, 0)
        self.assertIn("invalid result", result.errors[0])


if __name__ == "__main__":
    unittest.main()
