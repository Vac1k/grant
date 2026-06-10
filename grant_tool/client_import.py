from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select

from grant_tool.db.models import ApplicationHistory, JobType
from grant_tool.db.repositories import GrantRepository


VALID_HISTORY_RESULTS = {"won", "lost", "rejected", "not_submitted", "unknown"}


@dataclass(frozen=True)
class ImportResult:
    processed: int
    created: int
    updated: int
    skipped: int
    failed: int
    errors: list[str]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def split_list(value: str | None, *, separator: str = ";") -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(separator) if item.strip()]


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_date(value: str | None) -> date | None:
    value = empty_to_none(value)
    if value is None:
        return None
    return date.fromisoformat(value)


def parse_decimal(value: str | None, *, default: Decimal = Decimal("1")) -> Decimal:
    value = empty_to_none(value)
    if value is None:
        return default
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value}") from exc


def row_hash(row: dict[str, str]) -> str:
    normalized = "|".join(f"{key}={(row.get(key) or '').strip()}" for key in sorted(row))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _metadata_from_row(row: dict[str, str], path: Path, row_number: int) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "manual_seed": True,
        "source_file": str(path),
        "source_row_number": row_number,
        "source_row_hash": row_hash(row),
    }
    source_documents = split_list(row.get("source_documents"), separator="|")
    if source_documents:
        metadata["source_documents"] = source_documents
    confidence = empty_to_none(row.get("confidence"))
    if confidence:
        metadata["confidence"] = confidence
    extraction_notes = empty_to_none(row.get("extraction_notes"))
    if extraction_notes:
        metadata["extraction_notes"] = extraction_notes
    return metadata


def import_client_profiles(repository: GrantRepository, path: str | Path) -> ImportResult:
    csv_path = Path(path)
    rows = _read_csv(csv_path)
    job = repository.start_job(
        job_type=JobType.IMPORT_CLIENTS,
        job_metadata={"file": str(csv_path), "manual_seed": True},
    )
    errors: list[str] = []
    created = 0
    updated = 0
    skipped = 0
    failed = 0

    for index, row in enumerate(rows, start=2):
        name = empty_to_none(row.get("name"))
        if name is None:
            errors.append(f"row {index}: missing name")
            failed += 1
            continue

        slug = slugify(name)
        if not slug:
            errors.append(f"row {index}: could not generate slug for {name!r}")
            failed += 1
            continue

        existing = repository.get_client_profile_by_slug(slug)
        metadata = _metadata_from_row(row, csv_path, index)
        repository.upsert_client_profile(
            slug=slug,
            name=name,
            country=empty_to_none(row.get("country")),
            sector=empty_to_none(row.get("sector")),
            organization_type=empty_to_none(row.get("organization_type")),
            technologies=split_list(row.get("technologies")),
            product_description=empty_to_none(row.get("product_description")),
            risks=empty_to_none(row.get("risks")),
            target_topics=split_list(row.get("target_topics")),
            excluded_topics=split_list(row.get("excluded_topics")),
            profile_metadata=metadata,
            enabled=True,
        )
        if existing is None:
            created += 1
        else:
            updated += 1

    repository.increment_job_counters(
        job,
        processed=len(rows),
        created=created,
        updated=updated,
        skipped=skipped,
        failed=failed,
    )
    if failed:
        repository.mark_job_partial(job, error_message="Some client profile rows failed", job_metadata={"errors": errors})
    else:
        repository.finish_job_success(job)

    return ImportResult(len(rows), created, updated, skipped, failed, errors)


def import_application_history(repository: GrantRepository, path: str | Path) -> ImportResult:
    csv_path = Path(path)
    rows = _read_csv(csv_path)
    job = repository.start_job(
        job_type=JobType.IMPORT_HISTORY,
        job_metadata={"file": str(csv_path), "manual_seed": True},
    )
    errors: list[str] = []
    created = 0
    updated = 0
    skipped = 0
    failed = 0

    for index, row in enumerate(rows, start=2):
        client_name = empty_to_none(row.get("client_name"))
        grant_title = empty_to_none(row.get("grant_title"))
        result = empty_to_none(row.get("result")) or "unknown"

        if client_name is None or grant_title is None:
            errors.append(f"row {index}: missing client_name or grant_title")
            failed += 1
            continue
        if result not in VALID_HISTORY_RESULTS:
            errors.append(f"row {index}: invalid result {result!r}")
            failed += 1
            continue

        client = repository.get_client_profile_by_name(client_name)
        if client is None:
            errors.append(f"row {index}: client not found: {client_name}")
            skipped += 1
            continue

        grant_source = empty_to_none(row.get("grant_source"))
        program_name = empty_to_none(row.get("program_name"))
        existing = repository.session.scalar(
            select(ApplicationHistory).where(
                ApplicationHistory.client_profile_id == client.id,
                ApplicationHistory.grant_title == grant_title,
                (
                    ApplicationHistory.grant_source.is_(None)
                    if grant_source is None
                    else ApplicationHistory.grant_source == grant_source
                ),
                (
                    ApplicationHistory.program_name.is_(None)
                    if program_name is None
                    else ApplicationHistory.program_name == program_name
                ),
            )
        )
        metadata = _metadata_from_row(row, csv_path, index)
        notes = empty_to_none(row.get("notes"))
        if notes:
            metadata["manual_seed_notes"] = notes

        try:
            application_date = parse_date(row.get("application_date"))
            similarity_weight = parse_decimal(row.get("similarity_weight"))
        except ValueError as exc:
            errors.append(f"row {index}: {exc}")
            failed += 1
            continue

        repository.upsert_application_history(
            client_profile_id=client.id,
            client_name=client_name,
            grant_title=grant_title,
            grant_source=grant_source,
            program_name=program_name,
            application_date=application_date,
            result=result,
            country=empty_to_none(row.get("country")),
            applicant_type=empty_to_none(row.get("applicant_type")),
            topics=split_list(row.get("topics")),
            project_summary=empty_to_none(row.get("project_summary")),
            reusable_materials=empty_to_none(row.get("reusable_materials")),
            similarity_weight=similarity_weight,
            notes=notes,
            history_metadata=metadata,
        )
        if existing is None:
            created += 1
        else:
            updated += 1

    repository.increment_job_counters(
        job,
        processed=len(rows),
        created=created,
        updated=updated,
        skipped=skipped,
        failed=failed,
    )
    if failed or skipped:
        repository.mark_job_partial(
            job,
            error_message="Some application history rows failed or were skipped",
            job_metadata={"errors": errors},
        )
    else:
        repository.finish_job_success(job)

    return ImportResult(len(rows), created, updated, skipped, failed, errors)
