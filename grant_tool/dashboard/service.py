from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from grant_tool.db.models import ClientProfile, Grant, GrantClientMatch, JobRun, MatchRun, Source


PREPARED_QUALITY_TIERS = ("match_ready", "usable_with_warnings")
QUALITY_TIER_FILTERS = ("match_ready", "usable_with_warnings", "needs_review", "noise_rejected")


@dataclass(slots=True)
class DashboardStats:
    grants_total: int
    grants_open: int
    grants_new: int
    grants_manual_review: int
    grants_prepared: int
    grants_noise: int
    grants_unscored: int
    quality_tier_counts: dict[str, int]
    clients_total: int
    matches_total: int
    explained_matches: int
    sources_total: int
    latest_match_run: MatchRun | None


class DashboardService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def stats(self) -> DashboardStats:
        week_ago = datetime.now(UTC) - timedelta(days=7)
        latest_match_run = self.latest_match_run()
        quality_tier_counts = self.quality_tier_counts()
        return DashboardStats(
            grants_total=self._count(Grant),
            grants_open=self._scalar_int(select(func.count(Grant.id)).where(Grant.status.in_(["open", "active", "upcoming"]))),
            grants_new=self._scalar_int(select(func.count(Grant.id)).where(Grant.created_at >= week_ago)),
            grants_manual_review=self._scalar_int(select(func.count(Grant.id)).where(Grant.needs_manual_review.is_(True))),
            grants_prepared=sum(quality_tier_counts.get(tier, 0) for tier in PREPARED_QUALITY_TIERS),
            grants_noise=quality_tier_counts.get("noise_rejected", 0),
            grants_unscored=self._scalar_int(select(func.count(Grant.id)).where(Grant.quality_tier.is_(None))),
            quality_tier_counts=quality_tier_counts,
            clients_total=self._scalar_int(select(func.count(ClientProfile.id)).where(ClientProfile.enabled.is_(True))),
            matches_total=self._count(GrantClientMatch),
            explained_matches=self._scalar_int(select(func.count(GrantClientMatch.id)).where(GrantClientMatch.explanation.is_not(None))),
            sources_total=self._scalar_int(select(func.count(Source.id)).where(Source.enabled.is_(True))),
            latest_match_run=latest_match_run,
        )

    def latest_match_run(self) -> MatchRun | None:
        return self.session.scalar(select(MatchRun).order_by(MatchRun.started_at.desc()))

    def quality_tier_counts(self) -> dict[str, int]:
        query = (
            select(Grant.quality_tier, func.count(Grant.id))
            .where(Grant.quality_tier.is_not(None))
            .group_by(Grant.quality_tier)
        )
        return {tier: count for tier, count in self.session.execute(query)}

    def source_options(self) -> list[Source]:
        return list(self.session.scalars(select(Source).order_by(Source.slug)))

    def topic_options(self, *, limit: int = 120) -> list[str]:
        grants = self.session.scalars(select(Grant.topics).limit(limit)).all()
        topics = {topic for topics in grants for topic in (topics or []) if topic}
        return sorted(topics, key=str.lower)

    def latest_jobs(self, *, limit: int = 8) -> list[JobRun]:
        query = (
            select(JobRun)
            .options(selectinload(JobRun.source))
            .order_by(JobRun.started_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(query))

    def recent_grants(self, *, limit: int = 8) -> list[Grant]:
        query = (
            select(Grant)
            .options(selectinload(Grant.source))
            .order_by(Grant.updated_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(query))

    def grants(
        self,
        *,
        source_slug: str | None = None,
        status: str | None = None,
        topic: str | None = None,
        q: str | None = None,
        manual_review: bool | None = None,
        quality: str | None = None,
        limit: int = 100,
    ) -> list[Grant]:
        query = select(Grant).options(selectinload(Grant.source)).order_by(Grant.updated_at.desc())
        if source_slug:
            query = query.join(Source).where(Source.slug == source_slug)
        if status:
            query = query.where(Grant.status == status)
        if quality == "prepared":
            query = query.where(Grant.quality_tier.in_(PREPARED_QUALITY_TIERS))
        elif quality == "unscored":
            query = query.where(Grant.quality_tier.is_(None))
        elif quality in QUALITY_TIER_FILTERS:
            query = query.where(Grant.quality_tier == quality)
        if q:
            like = f"%{q.strip()}%"
            query = query.where(
                or_(
                    Grant.title.ilike(like),
                    Grant.summary.ilike(like),
                    Grant.description_text.ilike(like),
                    Grant.funder_name.ilike(like),
                    Grant.program_name.ilike(like),
                )
            )
        if manual_review is not None:
            query = query.where(Grant.needs_manual_review.is_(manual_review))

        rows = list(self.session.scalars(query.limit(max(limit * 3, limit))))
        if topic:
            normalized_topic = topic.lower()
            rows = [grant for grant in rows if normalized_topic in {item.lower() for item in (grant.topics or [])}]
        return rows[:limit]

    def clients(self) -> list[ClientProfile]:
        query = (
            select(ClientProfile)
            .options(selectinload(ClientProfile.application_history))
            .where(ClientProfile.enabled.is_(True))
            .order_by(ClientProfile.name)
        )
        return list(self.session.scalars(query))

    def matches(
        self,
        *,
        client_slug: str | None = None,
        min_score: Decimal | None = None,
        latest_only: bool = True,
        limit: int = 100,
    ) -> list[GrantClientMatch]:
        query = (
            select(GrantClientMatch)
            .options(
                selectinload(GrantClientMatch.client_profile),
                selectinload(GrantClientMatch.grant).selectinload(Grant.source),
                selectinload(GrantClientMatch.match_run),
            )
            .order_by(GrantClientMatch.score.desc(), GrantClientMatch.updated_at.desc())
            .limit(limit)
        )
        if latest_only:
            latest_match_run = self.latest_match_run()
            if latest_match_run is None:
                return []
            query = query.where(GrantClientMatch.match_run_id == latest_match_run.id)
        if client_slug:
            query = query.join(ClientProfile).where(ClientProfile.slug == client_slug)
        if min_score is not None:
            query = query.where(GrantClientMatch.score >= min_score)
        return list(self.session.scalars(query))

    def top_matches_by_client(self, *, limit_per_client: int = 3) -> dict[str, list[GrantClientMatch]]:
        grouped: dict[str, list[GrantClientMatch]] = {}
        for match in self.matches(limit=500):
            client_name = match.client_profile.name
            bucket = grouped.setdefault(client_name, [])
            if len(bucket) < limit_per_client:
                bucket.append(match)
        return grouped

    def manual_check_matches(self, *, limit: int = 20) -> list[GrantClientMatch]:
        matches = self.matches(limit=300)
        return [match for match in matches if match.manual_checks][:limit]

    def status_counts(self) -> list[tuple[str, int]]:
        query = select(Grant.status, func.count(Grant.id)).group_by(Grant.status).order_by(func.count(Grant.id).desc())
        return [(status or "unknown", count) for status, count in self.session.execute(query)]

    def source_counts(self) -> list[tuple[str, int]]:
        query = (
            select(Source.slug, func.count(Grant.id))
            .join(Grant, Grant.source_id == Source.id)
            .group_by(Source.slug)
            .order_by(func.count(Grant.id).desc())
        )
        return [(slug, count) for slug, count in self.session.execute(query)]

    def report_context(self) -> dict[str, Any]:
        return {
            "stats": self.stats(),
            "recent_grants": self.recent_grants(limit=12),
            "top_matches_by_client": self.top_matches_by_client(limit_per_client=3),
            "manual_check_matches": self.manual_check_matches(limit=20),
            "latest_jobs": self.latest_jobs(limit=10),
        }

    def _count(self, model: type[Any]) -> int:
        return self._scalar_int(select(func.count(model.id)))

    def _scalar_int(self, query: Any) -> int:
        value = self.session.scalar(query)
        return int(value or 0)
