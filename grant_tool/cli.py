from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from grant_tool.client_import import ImportResult, import_application_history, import_client_profiles
from grant_tool.config import get_settings
from grant_tool.db.repositories import GrantRepository
from grant_tool.db.session import SessionLocal
from grant_tool.embeddings import EmbeddingService, EmbeddingTarget
from grant_tool.explanations import MatchExplanationService
from grant_tool.extraction import FeatureExtractionService
from grant_tool.ingestion.connectors import CONNECTOR_CLASSES
from grant_tool.ingestion.service import IngestionService
from grant_tool.matching import ShortlistMatchingService
from grant_tool.sources import seed_mvp_sources


DEFAULT_CLIENTS_FILE = Path("data/manual_seed/client_profiles.manual.csv")
DEFAULT_HISTORY_FILE = Path("data/manual_seed/application_history.manual.csv")


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


def _print_import_result(label: str, result: ImportResult) -> None:
    print(
        f"{label}: processed={result.processed} created={result.created} "
        f"updated={result.updated} skipped={result.skipped} failed={result.failed}"
    )
    for error in result.errors:
        print(f"- {error}")


def _cmd_import_clients(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        result = import_client_profiles(repository, args.file)
        session.commit()

    _print_import_result("Client profiles import", result)


def _cmd_import_application_history(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        result = import_application_history(repository, args.file)
        session.commit()

    _print_import_result("Application history import", result)


def _cmd_import_manual_seed(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        clients_result = import_client_profiles(repository, args.clients_file)
        history_result = import_application_history(repository, args.history_file)
        session.commit()

    _print_import_result("Client profiles import", clients_result)
    _print_import_result("Application history import", history_result)


def _cmd_ingest(args: argparse.Namespace) -> None:
    source_slugs = list(CONNECTOR_CLASSES) if args.all else [args.source]

    with SessionLocal() as session:
        repository = GrantRepository(session)
        seed_mvp_sources(repository)
        service = IngestionService(repository=repository, connector_classes=CONNECTOR_CLASSES)

        for source_slug in source_slugs:
            summary = service.run_source(source_slug, limit=args.limit)
            print(
                f"{summary.source_slug}: {summary.status} "
                f"processed={summary.processed_count} "
                f"created={summary.created_count} "
                f"updated={summary.updated_count} "
                f"skipped={summary.skipped_count} "
                f"failed={summary.failed_count} "
                f"errors={len(summary.errors)} "
                f"job={summary.job.id}"
            )
        session.commit()


def _cmd_extract_features(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        service = FeatureExtractionService(repository=repository, use_llm=args.use_llm)
        summary = service.run_existing(source_slug=args.source, limit=args.limit)
        session.commit()

    print(
        f"Feature extraction: {summary.job.status} "
        f"processed={summary.processed_count} "
        f"updated={summary.updated_count} "
        f"skipped={summary.skipped_count} "
        f"failed={summary.failed_count} "
        f"errors={len(summary.errors)} "
        f"job={summary.job.id}"
    )
    for error in summary.errors:
        print(f"- {error}")


def _cmd_match(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        service = ShortlistMatchingService(repository=repository)
        summary = service.run(
            client_slug=args.client,
            grant_limit=args.grant_limit,
            top_n=args.top_n,
            min_score=args.min_score,
            name=args.name,
            use_vector=args.use_vector,
        )
        session.commit()

    print(
        f"Matching: {summary.match_run.status} "
        f"clients={summary.clients_count} "
        f"grants={summary.grants_count} "
        f"evaluated={summary.evaluated_count} "
        f"saved={summary.saved_count} "
        f"filtered={summary.filtered_count} "
        f"run={summary.match_run.id}"
    )


def _cmd_embed(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        service = EmbeddingService(repository=repository, provider_name=args.provider)
        summary = service.run(target=EmbeddingTarget(args.target), limit=args.limit, batch_size=args.batch_size)
        session.commit()

    print(
        f"Embeddings: {summary.job.status} "
        f"target={summary.target} "
        f"processed={summary.processed_count} "
        f"updated={summary.updated_count} "
        f"failed={summary.failed_count} "
        f"errors={len(summary.errors)} "
        f"job={summary.job.id}"
    )
    for error in summary.errors:
        print(f"- {error}")


def _cmd_explain_matches(args: argparse.Namespace) -> None:
    match_run_id = uuid.UUID(args.match_run_id) if args.match_run_id else None
    with SessionLocal() as session:
        repository = GrantRepository(session)
        service = MatchExplanationService(repository=repository, provider=args.provider)
        summary = service.run(match_run_id=match_run_id, limit=args.limit)
        session.commit()

    print(
        f"Explanations: {summary.job.status} "
        f"match_run={summary.match_run_id} "
        f"processed={summary.processed_count} "
        f"updated={summary.updated_count} "
        f"failed={summary.failed_count} "
        f"errors={len(summary.errors)} "
        f"job={summary.job.id}"
    )
    for error in summary.errors:
        print(f"- {error}")


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

    import_clients = subparsers.add_parser("import-clients", help="Import client profiles from CSV")
    import_clients.add_argument("--file", type=Path, default=DEFAULT_CLIENTS_FILE)
    import_clients.set_defaults(func=_cmd_import_clients)

    import_history = subparsers.add_parser(
        "import-application-history",
        help="Import application history from CSV",
    )
    import_history.add_argument("--file", type=Path, default=DEFAULT_HISTORY_FILE)
    import_history.set_defaults(func=_cmd_import_application_history)

    import_manual_seed = subparsers.add_parser(
        "import-manual-seed",
        help="Import curated manual seed clients and application history",
    )
    import_manual_seed.add_argument("--clients-file", type=Path, default=DEFAULT_CLIENTS_FILE)
    import_manual_seed.add_argument("--history-file", type=Path, default=DEFAULT_HISTORY_FILE)
    import_manual_seed.set_defaults(func=_cmd_import_manual_seed)

    ingest = subparsers.add_parser("ingest", help="Run grant ingestion")
    ingest_source = ingest.add_mutually_exclusive_group(required=True)
    ingest_source.add_argument("--source", choices=sorted(CONNECTOR_CLASSES), help="Source slug to ingest")
    ingest_source.add_argument("--all", action="store_true", help="Ingest all registered MVP sources")
    ingest.add_argument("--limit", type=int, default=20, help="Maximum grants per source")
    ingest.set_defaults(func=_cmd_ingest)

    extract_features = subparsers.add_parser(
        "extract-features",
        help="Run Stage 5 feature extraction for stored grants",
    )
    extract_features.add_argument("--source", choices=sorted(CONNECTOR_CLASSES), default=None)
    extract_features.add_argument("--limit", type=int, default=100)
    extract_features.add_argument(
        "--use-llm",
        action="store_true",
        help="Use optional LLM extraction when OPENAI_API_KEY is configured",
    )
    extract_features.set_defaults(func=_cmd_extract_features)

    match = subparsers.add_parser(
        "match",
        help="Run Stage 6 cheap filtering and shortlist matching",
    )
    match.add_argument("--client", default=None, help="Optional client profile slug")
    match.add_argument("--grant-limit", type=int, default=None, help="Maximum grants to evaluate")
    match.add_argument("--top-n", type=int, default=10, help="Matches to save per client")
    match.add_argument("--min-score", type=float, default=0.25, help="Minimum shortlist score")
    match.add_argument("--name", default=None, help="Optional match run name")
    match.add_argument("--use-vector", action="store_true", help="Use Stage 7 vector similarity when embeddings exist")
    match.set_defaults(func=_cmd_match)

    embed = subparsers.add_parser(
        "embed",
        help="Generate Stage 7 embeddings for grants, clients, and application history",
    )
    embed.add_argument("--target", choices=[target.value for target in EmbeddingTarget], default=EmbeddingTarget.ALL.value)
    embed.add_argument("--limit", type=int, default=None)
    embed.add_argument("--batch-size", type=int, default=16)
    embed.add_argument("--provider", choices=["hash", "openai"], default="hash")
    embed.set_defaults(func=_cmd_embed)

    explain_matches = subparsers.add_parser(
        "explain-matches",
        help="Generate Stage 8 explanations and risk notes for saved matches",
    )
    explain_matches.add_argument("--match-run-id", default=None, help="MatchRun id. Defaults to latest match run.")
    explain_matches.add_argument("--limit", type=int, default=20)
    explain_matches.add_argument("--provider", choices=["rule", "openai"], default="openai")
    explain_matches.set_defaults(func=_cmd_explain_matches)

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
