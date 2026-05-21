from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from grant_tool.db.models import ApplicationHistory, ClientProfile, Grant, MatchRun
from grant_tool.db.repositories import GrantRepository
from grant_tool.ingestion.utils import clean_text


MATCHING_VERSION = "stage6-shortlist-v1"


@dataclass(slots=True)
class MatchCandidate:
    grant: Grant
    client: ClientProfile
    score: Decimal
    keyword_score: Decimal
    history_score: Decimal
    hard_filter_passed: bool
    filter_reasons: list[str]
    manual_checks: list[str]
    evidence: dict[str, Any]


@dataclass(slots=True)
class MatchingSummary:
    match_run: MatchRun
    clients_count: int
    grants_count: int
    evaluated_count: int
    saved_count: int
    filtered_count: int


class ShortlistMatchingService:
    def __init__(self, *, repository: GrantRepository) -> None:
        self.repository = repository

    def run(
        self,
        *,
        client_slug: str | None = None,
        grant_limit: int | None = None,
        top_n: int = 10,
        min_score: Decimal | float | int = Decimal("0.2500"),
        name: str | None = None,
    ) -> MatchingSummary:
        min_score_decimal = self._decimal(min_score)
        clients = self._clients(client_slug=client_slug)
        grants = self.repository.list_grants_for_matching(limit=grant_limit)
        match_run = self.repository.create_match_run(
            name=name or "Stage 6 cheap shortlist",
            run_type="stage_6_shortlist",
            status="running",
            parameters={
                "client_slug": client_slug,
                "grant_limit": grant_limit,
                "top_n": top_n,
                "min_score": str(min_score_decimal),
                "matching_version": MATCHING_VERSION,
            },
        )

        evaluated = 0
        saved = 0
        filtered = 0

        for client in clients:
            history = self.repository.list_application_history_for_client(client.id)
            candidates: list[MatchCandidate] = []
            for grant in grants:
                evaluated += 1
                candidate = self.score(grant=grant, client=client, history=history)
                if not candidate.hard_filter_passed:
                    filtered += 1
                    continue
                if candidate.score < min_score_decimal:
                    filtered += 1
                    continue
                candidates.append(candidate)

            candidates.sort(key=lambda candidate: candidate.score, reverse=True)
            for rank, candidate in enumerate(candidates[:top_n], start=1):
                self.repository.save_match_result(
                    match_run_id=match_run.id,
                    grant_id=candidate.grant.id,
                    client_profile_id=candidate.client.id,
                    score=candidate.score,
                    rank=rank,
                    hard_filter_passed=candidate.hard_filter_passed,
                    filter_reasons=candidate.filter_reasons,
                    keyword_score=candidate.keyword_score,
                    history_score=candidate.history_score,
                    vector_score=None,
                    llm_score=None,
                    explanation=self._explanation(candidate),
                    risks_text=None,
                    manual_checks=candidate.manual_checks,
                    evidence=candidate.evidence,
                    match_metadata={
                        "matching_version": MATCHING_VERSION,
                        "score_breakdown": {
                            "keyword_score": str(candidate.keyword_score),
                            "history_score": str(candidate.history_score),
                            "final_score": str(candidate.score),
                        },
                    },
                )
                saved += 1

        match_run.status = "success"
        match_run.completed_at = datetime.now(UTC)
        match_run.notes = f"evaluated={evaluated} saved={saved} filtered={filtered}"
        self.repository.session.flush()
        return MatchingSummary(
            match_run=match_run,
            clients_count=len(clients),
            grants_count=len(grants),
            evaluated_count=evaluated,
            saved_count=saved,
            filtered_count=filtered,
        )

    def score(
        self,
        *,
        grant: Grant,
        client: ClientProfile,
        history: list[ApplicationHistory] | None = None,
    ) -> MatchCandidate:
        filter_passed, filter_reasons, manual_checks = self._hard_filter(grant=grant, client=client)
        keyword_score, keyword_evidence = self._keyword_score(grant=grant, client=client)
        history_score, history_evidence = self._history_score(grant=grant, history=history or [])

        score = (keyword_score * Decimal("0.75")) + (history_score * Decimal("0.25"))
        if grant.extraction_confidence is not None:
            score += min(Decimal(str(grant.extraction_confidence)), Decimal("1.0000")) * Decimal("0.05")
        if manual_checks:
            score -= Decimal("0.0500")
        if any(reason.startswith("excluded_topic:") for reason in filter_reasons):
            score -= Decimal("0.2000")
        score = max(Decimal("0.0000"), min(score, Decimal("1.0000"))).quantize(Decimal("0.0001"))

        return MatchCandidate(
            grant=grant,
            client=client,
            score=score,
            keyword_score=keyword_score,
            history_score=history_score,
            hard_filter_passed=filter_passed,
            filter_reasons=filter_reasons,
            manual_checks=manual_checks,
            evidence={
                "keyword": keyword_evidence,
                "history": history_evidence,
                "hard_filters": filter_reasons,
                "manual_checks": manual_checks,
            },
        )

    def _clients(self, *, client_slug: str | None) -> list[ClientProfile]:
        if client_slug:
            client = self.repository.get_client_profile_by_slug(client_slug)
            if client is None:
                raise ValueError(f"Client profile not found: {client_slug}")
            if not client.enabled:
                return []
            return [client]
        return self.repository.list_client_profiles(enabled_only=True)

    @staticmethod
    def _hard_filter(*, grant: Grant, client: ClientProfile) -> tuple[bool, list[str], list[str]]:
        reasons: list[str] = []
        manual_checks: list[str] = []

        if grant.status == "closed":
            reasons.append("closed_grant")
        elif grant.status == "unknown":
            manual_checks.append("grant status is unknown")

        if (
            grant.opportunity_type in {"training", "tender"}
            or grant.support_type in {"training", "procurement"}
            or ShortlistMatchingService._looks_like_non_grant_opportunity(grant)
        ):
            reasons.append(f"unsupported_opportunity_type:{grant.opportunity_type or grant.support_type}")

        if grant.deadline_at is not None and grant.deadline_at.date() < datetime.now(UTC).date():
            reasons.append("deadline_passed")
        elif grant.deadline_at is None:
            manual_checks.append("deadline missing")

        client_country = clean_text(client.country)
        grant_countries = {country.lower() for country in grant.countries or [] if country}
        if client_country and grant_countries:
            client_country_key = client_country.lower()
            if client_country_key not in grant_countries and "eu" not in grant_countries:
                reasons.append(f"country_mismatch:{client_country}")
            elif "eu" in grant_countries and client_country_key not in grant_countries:
                manual_checks.append("EU geography may require eligibility check")
        elif client_country and not grant_countries:
            manual_checks.append("grant countries missing")

        client_types = ShortlistMatchingService._client_applicant_types(client)
        grant_types = {value.lower() for value in grant.applicant_types or []}
        if client_types and grant_types and not ShortlistMatchingService._types_overlap(client_types, grant_types):
            reasons.append(f"applicant_type_mismatch:{client.organization_type or 'unknown'}")
        elif client_types and not grant_types:
            manual_checks.append("grant applicant types missing")

        grant_text = ShortlistMatchingService._grant_text(grant)
        nonprofit_only = any(
            token in grant_text
            for token in (
                "non-profit",
                "nonprofit",
                "non profit",
                "неприбутков",
                "громадські організації",
                "благодійні фонди",
                " огс ",
                "civil society",
                "charitable foundations",
            )
        )
        if nonprofit_only and "ngo" not in client_types:
            reasons.append("nonprofit_only_grant")

        excluded_topics = ShortlistMatchingService._normalised_set(client.excluded_topics)
        grant_topics = ShortlistMatchingService._normalised_set(grant.topics)
        for topic in sorted(excluded_topics & grant_topics):
            reasons.append(f"excluded_topic:{topic}")

        restrictions = f" {clean_text(grant.restrictions_text) or ''} ".lower()
        if restrictions:
            restriction_terms = set(client_types)
            if client_country:
                restriction_terms.add(client_country.lower())
            if "not eligible" in restrictions and any(term and term in restrictions for term in restriction_terms):
                reasons.append("restriction_conflict")
            elif any(token in restrictions for token in ("не можуть", "не допуска")):
                manual_checks.append("grant restrictions require review")

        hard_failed = any(
            reason.startswith(
                (
                    "closed_grant",
                    "deadline_passed",
                    "unsupported_opportunity_type",
                    "country_mismatch",
                    "applicant_type_mismatch",
                    "nonprofit_only_grant",
                    "restriction_conflict",
                )
            )
            for reason in reasons
        )
        return not hard_failed, reasons, manual_checks

    @staticmethod
    def _keyword_score(*, grant: Grant, client: ClientProfile) -> tuple[Decimal, dict[str, Any]]:
        grant_topics = ShortlistMatchingService._normalised_set(grant.topics)
        client_topics = ShortlistMatchingService._normalised_set(client.target_topics)
        excluded_topics = ShortlistMatchingService._normalised_set(client.excluded_topics)
        technologies = ShortlistMatchingService._normalised_set(client.technologies)
        grant_text = ShortlistMatchingService._grant_text(grant)
        client_types = ShortlistMatchingService._client_applicant_types(client)
        grant_types = {value.lower() for value in grant.applicant_types or []}

        topic_hits = sorted(grant_topics & client_topics)
        technology_hits = sorted(token for token in technologies if token and token in grant_text)
        applicant_hit = ShortlistMatchingService._types_overlap(client_types, grant_types)
        sector_hit = bool(client.sector and clean_text(client.sector).lower() in grant_text)
        excluded_hits = sorted(excluded_topics & grant_topics)

        score = Decimal("0.0000")
        if client_topics:
            score += Decimal(len(topic_hits)) / Decimal(max(len(client_topics), 1)) * Decimal("0.4500")
        if technologies:
            score += Decimal(min(len(technology_hits), len(technologies))) / Decimal(max(len(technologies), 1)) * Decimal("0.3000")
        if applicant_hit:
            score += Decimal("0.1500")
        if sector_hit:
            score += Decimal("0.1000")
        if excluded_hits:
            score -= Decimal("0.2000")

        score = max(Decimal("0.0000"), min(score, Decimal("1.0000"))).quantize(Decimal("0.0001"))
        return score, {
            "topic_hits": topic_hits,
            "technology_hits": technology_hits,
            "applicant_hit": applicant_hit,
            "sector_hit": sector_hit,
            "excluded_hits": excluded_hits,
        }

    @staticmethod
    def _history_score(*, grant: Grant, history: list[ApplicationHistory]) -> tuple[Decimal, dict[str, Any]]:
        if not history:
            return Decimal("0.0000"), {"matched_history": []}

        grant_topics = ShortlistMatchingService._normalised_set(grant.topics)
        grant_text = ShortlistMatchingService._grant_text(grant)
        matched: list[dict[str, Any]] = []
        best = Decimal("0.0000")

        for item in history:
            item_topics = ShortlistMatchingService._normalised_set(item.topics)
            topic_overlap = grant_topics & item_topics
            text_hits = [
                value
                for value in (item.grant_title, item.program_name, item.grant_source)
                if value and clean_text(value).lower() in grant_text
            ]
            base = Decimal("0.0000")
            if item_topics:
                base += Decimal(len(topic_overlap)) / Decimal(max(len(item_topics), 1)) * Decimal("0.5000")
            if text_hits:
                base += Decimal("0.2500")
            if item.reusable_materials:
                base += Decimal("0.1500")
            if item.applicant_type and clean_text(item.applicant_type).lower() in {value.lower() for value in grant.applicant_types or []}:
                base += Decimal("0.1000")

            weight = Decimal(str(item.similarity_weight or 1))
            weighted = min(base * weight, Decimal("1.0000"))
            if weighted > Decimal("0.0000"):
                matched.append(
                    {
                        "grant_title": item.grant_title,
                        "result": item.result,
                        "topic_hits": sorted(topic_overlap),
                        "text_hits": [clean_text(value) for value in text_hits],
                        "reusable_materials": bool(item.reusable_materials),
                        "score": str(weighted.quantize(Decimal("0.0001"))),
                    }
                )
            best = max(best, weighted)

        return best.quantize(Decimal("0.0001")), {"matched_history": matched[:5]}

    @staticmethod
    def _client_applicant_types(client: ClientProfile) -> set[str]:
        text = f"{client.organization_type or ''} {client.sector or ''} {client.product_description or ''}".lower()
        result: set[str] = set()
        if any(token in text for token in ("ngo", "non-profit", "nonprofit", "громад", "благод")):
            result.add("ngo")
        if any(token in text for token in ("startup", "стартап")):
            result.add("startup")
        if any(token in text for token in ("sme", "мсп", "мсб", "small", "medium")):
            result.add("sme")
        if any(token in text for token in ("company", "business", "підприєм", "компан", "llc", "тов")):
            result.add("company")
        return result

    @staticmethod
    def _looks_like_non_grant_opportunity(grant: Grant) -> bool:
        title = f" {clean_text(grant.title) or ''} ".lower()
        text = ShortlistMatchingService._grant_text(grant)
        if any(token in title for token in (" набір на ", " табір ", " стипенді", " тренінг", " training", " workshop")):
            return True
        if any(token in title for token in (" академі", " academy")) and not any(token in title for token in ("грант", "grant")):
            return True
        if any(token in text[:900] for token in ("запрошує на тренінг", "реєстрація на тренінг", "набір учасників")):
            return True
        return False

    @staticmethod
    def _types_overlap(client_types: set[str], grant_types: set[str]) -> bool:
        if not client_types or not grant_types:
            return False
        if client_types & grant_types:
            return True
        if "company" in client_types and grant_types & {"sme", "startup"}:
            return True
        if "sme" in client_types and grant_types & {"company", "startup"}:
            return True
        if "startup" in client_types and grant_types & {"company", "sme"}:
            return True
        return False

    @staticmethod
    def _normalised_set(values: list[str] | None) -> set[str]:
        return {cleaned.lower() for value in values or [] if (cleaned := clean_text(value))}

    @staticmethod
    def _grant_text(grant: Grant) -> str:
        parts = [
            grant.title,
            grant.summary,
            grant.description_text,
            grant.eligibility_text,
            " ".join(grant.topics or []),
            " ".join(grant.keywords or []),
            " ".join(grant.applicant_types or []),
        ]
        return f" {clean_text(' '.join(part for part in parts if part)).lower()} "

    @staticmethod
    def _explanation(candidate: MatchCandidate) -> str:
        keyword = candidate.evidence.get("keyword", {})
        history = candidate.evidence.get("history", {})
        parts = []
        topic_hits = keyword.get("topic_hits") or []
        technology_hits = keyword.get("technology_hits") or []
        if topic_hits:
            parts.append("topic fit: " + ", ".join(topic_hits))
        if technology_hits:
            parts.append("technology fit: " + ", ".join(technology_hits))
        if keyword.get("applicant_hit"):
            parts.append("applicant type fit")
        if history.get("matched_history"):
            parts.append("similar application history")
        if not parts:
            parts.append("basic shortlist score passed")
        return "; ".join(parts)

    @staticmethod
    def _decimal(value: Decimal | float | int) -> Decimal:
        return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
