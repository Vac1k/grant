from __future__ import annotations

import argparse
import uuid

from grant_tool.config import get_settings
from grant_tool.db.repositories import GrantRepository
from grant_tool.db.session import SessionLocal
from grant_tool.sources import seed_mvp_sources


def _print_default() -> None:
    settings = get_settings()
    print(f"{settings.app_name} ({settings.app_env})")
    print("Run the API with: uvicorn grant_tool.main:app --reload")


def _cmd_seed_sources(_args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        job, sources = seed_mvp_sources(repository)
        session.commit()

    print(f"Seeded {len(sources)} MVP sources")
    print(f"Job {job.id}: {job.status}")
    for source in sources:
        print(f"- {source.slug}: {source.name}")


def _cmd_jobs_list(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        jobs = repository.list_jobs(limit=args.limit, job_type=args.type)

        if not jobs:
            print("No jobs found")
            return

        for job in jobs:
            source_slug = job.source.slug if job.source else "-"
            print(
                f"{job.id}  {job.job_type}  {job.status}  "
                f"source={source_slug}  processed={job.processed_count}  "
                f"created={job.created_count}  updated={job.updated_count}  "
                f"failed={job.failed_count}"
            )


def _cmd_jobs_show(args: argparse.Namespace) -> None:
    job_id = uuid.UUID(args.job_id)
    with SessionLocal() as session:
        repository = GrantRepository(session)
        job = repository.get_job(job_id)

        if job is None:
            raise SystemExit(f"Job not found: {job_id}")

        source_slug = job.source.slug if job.source else "-"
        print(f"id: {job.id}")
        print(f"type: {job.job_type}")
        print(f"status: {job.status}")
        print(f"source: {source_slug}")
        print(f"started_at: {job.started_at}")
        print(f"finished_at: {job.finished_at}")
        print(f"processed_count: {job.processed_count}")
        print(f"created_count: {job.created_count}")
        print(f"updated_count: {job.updated_count}")
        print(f"skipped_count: {job.skipped_count}")
        print(f"failed_count: {job.failed_count}")
        print(f"error_message: {job.error_message}")
        print(f"job_metadata: {job.job_metadata}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grant-tool")
    subparsers = parser.add_subparsers(dest="command")

    seed_sources = subparsers.add_parser("seed-sources", help="Create or update MVP grant sources")
    seed_sources.set_defaults(func=_cmd_seed_sources)

    jobs = subparsers.add_parser("jobs", help="Inspect job history")
    job_subparsers = jobs.add_subparsers(dest="jobs_command", required=True)

    jobs_list = job_subparsers.add_parser("list", help="List recent jobs")
    jobs_list.add_argument("--limit", type=int, default=20)
    jobs_list.add_argument("--type", default=None, help="Filter by job type")
    jobs_list.set_defaults(func=_cmd_jobs_list)

    jobs_show = job_subparsers.add_parser("show", help="Show one job")
    jobs_show.add_argument("job_id")
    jobs_show.set_defaults(func=_cmd_jobs_show)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        _print_default()
        return

    args.func(args)


if __name__ == "__main__":
    main()
