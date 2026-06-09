from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from grant_tool.client_import import ImportResult, import_application_history, import_client_profiles
from grant_tool.config import get_settings
from grant_tool.db.repositories import DataAuditSourceRow, GrantRepository, SearchQualityGateRow, SearchSourceReportRow
from grant_tool.db.session import SessionLocal
from grant_tool.deduplication import DeduplicationSummary, GrantDeduplicationService
from grant_tool.embeddings import EmbeddingService, EmbeddingTarget
from grant_tool.explanations import MatchExplanationService
from grant_tool.extraction import FeatureExtractionService
from grant_tool.ingestion.connectors import CONNECTOR_CLASSES
from grant_tool.ingestion.service import IngestionService
from grant_tool.ingestion.types import DiscoveryMode
from grant_tool.matching import ShortlistMatchingService
from grant_tool.sources import QUALITY_GATE_EXCLUDED_SOURCE_SLUGS, QUALITY_GATE_REQUIRED_SOURCE_SLUGS, seed_mvp_sources


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

    print(f"Seeded {len(sources)} configured sources")
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


def _format_search_report(rows: list[SearchSourceReportRow]) -> list[str]:
    if not rows:
        return ["No sources found"]

    lines = [
        "Search source report",
        (
            "source | enabled | discovered | grants | new/known | detail fetched/skipped/failed | "
            "open/unknown/manual | latest job | refresh due/refreshed | last seen"
        ),
        "-" * 156,
    ]
    for row in rows:
        latest_job = row.latest_job_status or "-"
        if row.latest_job_status:
            latest_job = (
                f"{row.latest_job_status} "
                f"p={row.latest_job_processed} c={row.latest_job_created} "
                f"u={row.latest_job_updated} s={row.latest_job_skipped} f={row.latest_job_failed}"
            )
        last_seen = row.last_seen_at.isoformat() if row.last_seen_at else "-"
        lines.append(
            f"{row.source_slug} | "
            f"{'yes' if row.enabled else 'no'} | "
            f"{row.discovered_total} | "
            f"{row.grants_total} | "
            f"{row.discovery_new}/{row.discovery_known} | "
            f"{row.detail_fetched}/{row.detail_skipped_known}/{row.detail_failed} | "
            f"{row.grants_open}/{row.grants_unknown}/{row.grants_manual_review} | "
            f"{latest_job} | "
            f"{row.latest_job_refresh_due}/{row.latest_job_refreshed_known} | "
            f"{last_seen}"
        )
    return lines


def _cmd_search_report(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        rows = repository.search_source_report(source_slug=args.source)

    for line in _format_search_report(rows):
        print(line)


def _format_quality_gate_report(rows: list[SearchQualityGateRow]) -> list[str]:
    if not rows:
        return ["No quality gate rows found"]

    required_rows = [row for row in rows if row.required]
    passed_count = sum(1 for row in required_rows if row.passed)
    status = "passed" if passed_count == len(required_rows) else "blocked"
    lines = [
        f"Search quality gate: {status} ({passed_count}/{len(required_rows)} required sources passed)",
        "source | required | quality/required | total | rejected | status | approved samples",
        "-" * 132,
    ]
    for row in rows:
        samples = "; ".join(sample.title[:80] for sample in row.samples) or "-"
        row_status = "passed" if row.passed else "blocked"
        if not row.required:
            row_status = "excluded"
        lines.append(
            f"{row.source_slug} | "
            f"{'yes' if row.required else 'no'} | "
            f"{row.quality_approved_count}/{row.required_count} | "
            f"{row.grants_total} | "
            f"{row.rejected_count} | "
            f"{row_status} | "
            f"{samples}"
        )
    return lines


def _cmd_quality_gate(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        rows = repository.search_quality_gate_report(
            required_source_slugs=list(QUALITY_GATE_REQUIRED_SOURCE_SLUGS),
            excluded_source_slugs=list(QUALITY_GATE_EXCLUDED_SOURCE_SLUGS),
            required_count=args.required_count,
            sample_limit=args.sample_limit,
        )

    for line in _format_quality_gate_report(rows):
        print(line)

    required_rows = [row for row in rows if row.required]
    if not args.no_fail and any(not row.passed for row in required_rows):
        raise SystemExit(1)


def _format_count_percent(count: int, total: int) -> str:
    if total <= 0:
        return "0/0 (0.0%)"
    return f"{count}/{total} ({(count / total) * 100:.1f}%)"


def _format_data_audit_report(rows: list[DataAuditSourceRow]) -> list[str]:
    if not rows:
        return ["No sources found"]

    total_grants = sum(row.grants_total for row in rows)
    total_manual = sum(row.manual_review_count for row in rows)
    total_weak = sum(row.weak_record_count for row in rows)
    total_noise = sum(row.noise_candidate_count for row in rows)
    lines = [
        "Grant data audit",
        (
            f"totals: grants={total_grants} "
            f"manual_review={_format_count_percent(total_manual, total_grants)} "
            f"weak_records={_format_count_percent(total_weak, total_grants)} "
            f"noise_candidates={_format_count_percent(total_noise, total_grants)}"
        ),
    ]

    for row in rows:
        status_counts = ", ".join(f"{status}={count}" for status, count in sorted(row.status_counts.items())) or "-"
        completeness = "; ".join(
            f"{field.field_name}={_format_count_percent(field.populated_count, field.total_count)}"
            for field in row.field_completeness
        )
        weakest_fields = sorted(
            row.field_completeness,
            key=lambda field: (field.populated_count / field.total_count) if field.total_count else 1,
        )[:5]
        weakest_field_text = ", ".join(
            f"{field.field_name} {field.missing_count} missing"
            for field in weakest_fields
            if field.missing_count
        ) or "none"

        lines.extend(
            [
                "",
                f"source: {row.source_slug}",
                f"  grants: {row.grants_total}",
                f"  status: {status_counts}",
                f"  manual review: {_format_count_percent(row.manual_review_count, row.grants_total)}",
                f"  weak records: {_format_count_percent(row.weak_record_count, row.grants_total)}",
                f"  noise candidates: {_format_count_percent(row.noise_candidate_count, row.grants_total)}",
                f"  weakest fields: {weakest_field_text}",
                f"  completeness: {completeness}",
            ]
        )

        if row.weak_samples:
            lines.append("  weak samples:")
            for sample in row.weak_samples:
                reason_text = ", ".join(sample.reasons)
                review_text = f" | review: {sample.manual_review_reason}" if sample.manual_review_reason else ""
                lines.append(f"    - {sample.title[:100]} [{sample.status}]: {reason_text}{review_text} | {sample.source_url}")
        if row.noise_samples:
            lines.append("  noise samples:")
            for sample in row.noise_samples:
                reason_text = ", ".join(sample.reasons)
                lines.append(f"    - {sample.title[:100]} [{sample.status}]: {reason_text} | {sample.source_url}")
    return lines


def _cmd_data_audit(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        rows = repository.data_audit_report(source_slug=args.source, sample_limit=args.sample_limit)

    for line in _format_data_audit_report(rows):
        print(line)


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
            summary = service.run_source(source_slug, limit=args.limit, mode=args.mode)
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


def _format_deduplication_summary(summary: DeduplicationSummary) -> list[str]:
    lines = [
        (
            "Deduplication: "
            f"processed={summary.processed_count} "
            f"candidates={summary.candidate_count} "
            f"duplicate_pairs={summary.duplicate_pair_count} "
            f"duplicate_groups={summary.duplicate_group_count} "
            f"duplicate_records={summary.duplicate_record_count} "
            f"dry_run={'yes' if summary.dry_run else 'no'}"
        )
    ]
    if summary.groups:
        lines.append("duplicate groups:")
        for group in summary.groups[:10]:
            best_score = max((candidate.score for candidate in group.candidates), default=0)
            lines.append(
                f"  - {group.group_id}: primary={group.primary_grant_id} "
                f"size={len(group.grant_ids)} best_score={best_score}"
            )
    if summary.candidates:
        lines.append("top candidates:")
        for candidate in summary.candidates[:10]:
            reasons = ", ".join(candidate.reasons)
            lines.append(
                f"  - {candidate.score} duplicate={'yes' if candidate.duplicate else 'no'} "
                f"{candidate.left_grant_id} <> {candidate.right_grant_id}: {reasons}"
            )
    return lines


def _cmd_deduplicate(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        repository = GrantRepository(session)
        service = GrantDeduplicationService(repository=repository)
        summary = service.run(
            source_slug=args.source,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            session.commit()

    for line in _format_deduplication_summary(summary):
        print(line)


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

    seed_sources = subparsers.add_parser("seed-sources", help="Create or update configured grant sources")
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

    search_report = subparsers.add_parser("search-report", help="Show operational status for search/link extraction")
    search_report.add_argument("--source", default=None, help="Optional source slug")
    search_report.set_defaults(func=_cmd_search_report)

    quality_gate = subparsers.add_parser("quality-gate", help="Check Step 9 quality gate for search sources")
    quality_gate.add_argument("--required-count", type=int, default=10)
    quality_gate.add_argument("--sample-limit", type=int, default=10)
    quality_gate.add_argument("--no-fail", action="store_true", help="Print report without non-zero exit on blocked gate")
    quality_gate.set_defaults(func=_cmd_quality_gate)

    data_audit = subparsers.add_parser("data-audit", help="Audit normalized grant data quality")
    data_audit.add_argument("--source", default=None, help="Optional source slug")
    data_audit.add_argument("--sample-limit", type=int, default=5)
    data_audit.set_defaults(func=_cmd_data_audit)

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
    ingest_source.add_argument("--all", action="store_true", help="Ingest all registered sources")
    ingest.add_argument("--limit", type=int, default=20, help="Maximum grants per source")
    ingest.add_argument(
        "--mode",
        choices=[mode.value for mode in DiscoveryMode],
        default=DiscoveryMode.INCREMENTAL.value,
        help="Discovery mode: incremental skips known detail items; backfill refetches them",
    )
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

    deduplicate = subparsers.add_parser(
        "deduplicate",
        help="Run Step 5 duplicate candidate detection for stored grants",
    )
    deduplicate.add_argument("--source", choices=sorted(CONNECTOR_CLASSES), default=None)
    deduplicate.add_argument("--limit", type=int, default=None)
    deduplicate.add_argument("--dry-run", action="store_true", help="Compute candidates without writing metadata")
    deduplicate.set_defaults(func=_cmd_deduplicate)

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
