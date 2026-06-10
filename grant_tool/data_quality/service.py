from __future__ import annotations

from dataclasses import dataclass, field

from grant_tool.data_quality.scoring import (
    DEFAULT_MIN_MATCHING_QUALITY_SCORE,
    QUALITY_SCORING_VERSION,
    apply_grant_quality_score,
    compute_grant_quality_score,
)
from grant_tool.db.models import JobRun, JobType
from grant_tool.db.repositories import GrantRepository


@dataclass(slots=True)
class QualityScoreSourceRow:
    source_slug: str
    grants_total: int
    average_score: float
    low_score_count: int
    matching_ready_count: int
    tier_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class QualityScoringSummary:
    job: JobRun
    processed_count: int
    average_score: float
    low_score_count: int
    matching_ready_count: int
    tier_counts: dict[str, int]
    rows: list[QualityScoreSourceRow]
    min_matching_quality_score: int
    dry_run: bool


class QualityScoringService:
    def __init__(self, *, repository: GrantRepository) -> None:
        self.repository = repository

    def run(
        self,
        *,
        source_slug: str | None = None,
        limit: int | None = None,
        dry_run: bool = False,
        min_matching_quality_score: int = DEFAULT_MIN_MATCHING_QUALITY_SCORE,
    ) -> QualityScoringSummary:
        grants = self.repository.list_grants_for_quality_scoring(source_slug=source_slug, limit=limit)
        job = self.repository.start_job(
            job_type=JobType.QUALITY_SCORE,
            job_metadata={
                "version": QUALITY_SCORING_VERSION,
                "source_slug": source_slug,
                "limit": limit,
                "dry_run": dry_run,
                "min_matching_quality_score": min_matching_quality_score,
            },
        )

        tier_counts: dict[str, int] = {}
        per_source: dict[str, QualityScoreSourceRow] = {}
        source_score_totals: dict[str, int] = {}
        score_total = 0
        low_score_count = 0
        matching_ready_count = 0

        for grant in grants:
            if dry_run:
                result = compute_grant_quality_score(grant, min_matching_quality_score=min_matching_quality_score)
            else:
                result = apply_grant_quality_score(grant, min_matching_quality_score=min_matching_quality_score)
            self.repository.increment_job_counters(job, processed=1, updated=0 if dry_run else 1)

            slug = grant.source.slug if grant.source is not None else "unknown"
            row = per_source.get(slug)
            if row is None:
                row = QualityScoreSourceRow(
                    source_slug=slug,
                    grants_total=0,
                    average_score=0.0,
                    low_score_count=0,
                    matching_ready_count=0,
                )
                per_source[slug] = row
                source_score_totals[slug] = 0
            row.grants_total += 1
            source_score_totals[slug] += result.score
            row.tier_counts[result.tier.value] = row.tier_counts.get(result.tier.value, 0) + 1
            tier_counts[result.tier.value] = tier_counts.get(result.tier.value, 0) + 1
            score_total += result.score
            if result.score < min_matching_quality_score:
                row.low_score_count += 1
                low_score_count += 1
            if result.matching_ready:
                row.matching_ready_count += 1
                matching_ready_count += 1

        for slug, row in per_source.items():
            row.average_score = round(source_score_totals[slug] / row.grants_total, 1) if row.grants_total else 0.0

        self.repository.finish_job_success(
            job,
            job_metadata={
                "processed": len(grants),
                "tier_counts": tier_counts,
                "low_score_count": low_score_count,
                "matching_ready_count": matching_ready_count,
            },
        )

        return QualityScoringSummary(
            job=job,
            processed_count=len(grants),
            average_score=round(score_total / len(grants), 1) if grants else 0.0,
            low_score_count=low_score_count,
            matching_ready_count=matching_ready_count,
            tier_counts=tier_counts,
            rows=sorted(per_source.values(), key=lambda row: row.source_slug),
            min_matching_quality_score=min_matching_quality_score,
            dry_run=dry_run,
        )
