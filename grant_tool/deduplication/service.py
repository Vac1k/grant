from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Any

from grant_tool.data_quality import GrantQualityTier, SourceFamily, evaluate_grant_quality_contract
from grant_tool.db.models import Grant
from grant_tool.db.repositories import GrantRepository
from grant_tool.ingestion.utils import canonicalize_url, clean_text


DEDUPLICATION_RULE_VERSION = "data-preparation-step5-v1"
DEFAULT_CANDIDATE_THRESHOLD = Decimal("0.7400")
DEFAULT_DUPLICATE_THRESHOLD = Decimal("0.8600")


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    left_grant_id: str
    right_grant_id: str
    score: Decimal
    reasons: tuple[str, ...]
    duplicate: bool


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    group_id: str
    primary_grant_id: str
    grant_ids: tuple[str, ...]
    candidates: tuple[DuplicateCandidate, ...]


@dataclass(frozen=True, slots=True)
class DeduplicationSummary:
    processed_count: int
    candidate_count: int
    duplicate_pair_count: int
    duplicate_group_count: int
    duplicate_record_count: int
    candidates: tuple[DuplicateCandidate, ...]
    groups: tuple[DuplicateGroup, ...]
    dry_run: bool = False


class GrantDeduplicationService:
    def __init__(self, *, repository: GrantRepository) -> None:
        self.repository = repository

    def run(
        self,
        *,
        source_slug: str | None = None,
        limit: int | None = None,
        dry_run: bool = False,
        candidate_threshold: Decimal = DEFAULT_CANDIDATE_THRESHOLD,
        duplicate_threshold: Decimal = DEFAULT_DUPLICATE_THRESHOLD,
    ) -> DeduplicationSummary:
        grants = self.repository.list_grants_for_deduplication(source_slug=source_slug, limit=limit)
        grant_by_id = {str(grant.id): grant for grant in grants}
        candidates = self._find_candidates(
            grants,
            candidate_threshold=candidate_threshold,
            duplicate_threshold=duplicate_threshold,
        )
        groups = self._duplicate_groups(
            grants,
            candidates,
            duplicate_threshold=duplicate_threshold,
        )

        if not dry_run:
            self._write_deduplication_metadata(grants, candidates, groups, grant_by_id=grant_by_id)
            self.repository.session.flush()

        duplicate_primary_ids = {group.primary_grant_id for group in groups}
        duplicate_group_ids = {grant_id for group in groups for grant_id in group.grant_ids}
        duplicate_record_count = len(duplicate_group_ids - duplicate_primary_ids)
        return DeduplicationSummary(
            processed_count=len(grants),
            candidate_count=len(candidates),
            duplicate_pair_count=sum(1 for candidate in candidates if candidate.score >= duplicate_threshold),
            duplicate_group_count=len(groups),
            duplicate_record_count=duplicate_record_count,
            candidates=tuple(candidates),
            groups=tuple(groups),
            dry_run=dry_run,
        )

    def _find_candidates(
        self,
        grants: list[Grant],
        *,
        candidate_threshold: Decimal,
        duplicate_threshold: Decimal,
    ) -> list[DuplicateCandidate]:
        candidates: list[DuplicateCandidate] = []
        for index, left in enumerate(grants):
            for right in grants[index + 1 :]:
                score, reasons = self._score_pair(left, right)
                if score < candidate_threshold:
                    continue
                candidates.append(
                    DuplicateCandidate(
                        left_grant_id=str(left.id),
                        right_grant_id=str(right.id),
                        score=score,
                        reasons=tuple(reasons),
                        duplicate=score >= duplicate_threshold,
                    )
                )
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)

    def _score_pair(self, left: Grant, right: Grant) -> tuple[Decimal, list[str]]:
        score = Decimal("0.0000")
        reasons: list[str] = []

        if _url_keys(left) & _url_keys(right):
            score += Decimal("0.5500")
            reasons.append("same_canonical_or_application_url")

        left_title = _normalized_title(left.title)
        right_title = _normalized_title(right.title)
        title_similarity = _title_similarity(left_title, right_title)
        if left_title and right_title:
            if left_title == right_title:
                score += Decimal("0.4500")
                reasons.append("exact_normalized_title")
            elif title_similarity >= Decimal("0.9200"):
                score += Decimal("0.4000")
                reasons.append(f"very_similar_title:{title_similarity}")
            elif title_similarity >= Decimal("0.8400"):
                score += Decimal("0.3200")
                reasons.append(f"similar_title:{title_similarity}")
            elif title_similarity >= Decimal("0.7600"):
                score += Decimal("0.2200")
                reasons.append(f"weak_title_similarity:{title_similarity}")

        if _same_deadline(left, right):
            score += Decimal("0.1400")
            reasons.append("same_deadline")

        if _same_clean_text(left.funder_name, right.funder_name):
            score += Decimal("0.1000")
            reasons.append("same_funder")

        if _same_clean_text(left.program_name, right.program_name):
            score += Decimal("0.0800")
            reasons.append("same_program")

        if _same_amount(left, right):
            score += Decimal("0.0900")
            reasons.append("same_amount_and_currency")
        elif left.currency and right.currency and left.currency == right.currency:
            score += Decimal("0.0300")
            reasons.append("same_currency")

        taxonomy_overlap = _taxonomy_overlap(left, right)
        if taxonomy_overlap:
            score += Decimal("0.0400")
            reasons.append(f"taxonomy_overlap:{','.join(taxonomy_overlap[:4])}")

        source_pair = {(_source_slug(left) or ""), (_source_slug(right) or "")}
        if source_pair == {"eu-funding", "eufundingportal-eu"} and title_similarity >= Decimal("0.7600"):
            score += Decimal("0.0700")
            reasons.append("official_eu_aggregator_pair")
        elif _source_slug(left) == _source_slug(right) and title_similarity >= Decimal("0.8400"):
            score += Decimal("0.0500")
            reasons.append("same_source_similar_title")

        if not reasons:
            return Decimal("0.0000"), []
        if "same_canonical_or_application_url" not in reasons and not _has_meaningful_title(left_title, right_title):
            return Decimal("0.0000"), []
        return min(score, Decimal("1.0000")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), reasons

    def _duplicate_groups(
        self,
        grants: list[Grant],
        candidates: list[DuplicateCandidate],
        *,
        duplicate_threshold: Decimal,
    ) -> list[DuplicateGroup]:
        parent = {str(grant.id): str(grant.id) for grant in grants}

        def find(item: str) -> str:
            while parent[item] != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        def union(left: str, right: str) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        duplicate_candidates = [candidate for candidate in candidates if candidate.score >= duplicate_threshold]
        for candidate in duplicate_candidates:
            union(candidate.left_grant_id, candidate.right_grant_id)

        grouped_ids: dict[str, list[str]] = {}
        for grant in grants:
            grant_id = str(grant.id)
            grouped_ids.setdefault(find(grant_id), []).append(grant_id)

        grant_by_id = {str(grant.id): grant for grant in grants}
        groups: list[DuplicateGroup] = []
        for grant_ids in grouped_ids.values():
            if len(grant_ids) < 2:
                continue
            group_grants = [grant_by_id[grant_id] for grant_id in grant_ids]
            primary = _choose_primary(group_grants)
            group_candidate_ids = set(grant_ids)
            group_candidates = tuple(
                candidate
                for candidate in duplicate_candidates
                if candidate.left_grant_id in group_candidate_ids and candidate.right_grant_id in group_candidate_ids
            )
            group_id = _group_id(grant_ids)
            groups.append(
                DuplicateGroup(
                    group_id=group_id,
                    primary_grant_id=str(primary.id),
                    grant_ids=tuple(sorted(grant_ids)),
                    candidates=group_candidates,
                )
            )
        return sorted(groups, key=lambda group: (len(group.grant_ids), group.group_id), reverse=True)

    def _write_deduplication_metadata(
        self,
        grants: list[Grant],
        candidates: list[DuplicateCandidate],
        groups: list[DuplicateGroup],
        *,
        grant_by_id: dict[str, Grant],
    ) -> None:
        candidates_by_grant: dict[str, list[DuplicateCandidate]] = {str(grant.id): [] for grant in grants}
        for candidate in candidates:
            candidates_by_grant[candidate.left_grant_id].append(candidate)
            candidates_by_grant[candidate.right_grant_id].append(candidate)

        group_by_grant: dict[str, DuplicateGroup] = {}
        for group in groups:
            for grant_id in group.grant_ids:
                group_by_grant[grant_id] = group

        for grant in grants:
            grant_id = str(grant.id)
            group = group_by_grant.get(grant_id)
            grant_candidates = sorted(candidates_by_grant.get(grant_id, []), key=lambda candidate: candidate.score, reverse=True)
            is_duplicate = group is not None and group.primary_grant_id != grant_id
            potential_duplicate = bool(grant_candidates)
            max_score = grant_candidates[0].score if grant_candidates else Decimal("0.0000")
            metadata = dict(grant.extraction_metadata or {})
            metadata["deduplication"] = {
                "version": DEDUPLICATION_RULE_VERSION,
                "is_duplicate": is_duplicate,
                "is_primary": bool(group and group.primary_grant_id == grant_id),
                "potential_duplicate": potential_duplicate,
                "duplicate_group_id": group.group_id if group else None,
                "duplicate_group_size": len(group.grant_ids) if group else 1,
                "primary_grant_id": group.primary_grant_id if group else None,
                "max_candidate_score": str(max_score),
                "candidate_count": len(grant_candidates),
                "candidates": [
                    _candidate_metadata(candidate, grant_id=grant_id, grant_by_id=grant_by_id)
                    for candidate in grant_candidates[:5]
                ],
            }
            grant.extraction_metadata = metadata


def _candidate_metadata(
    candidate: DuplicateCandidate,
    *,
    grant_id: str,
    grant_by_id: dict[str, Grant],
) -> dict[str, Any]:
    other_id = candidate.right_grant_id if candidate.left_grant_id == grant_id else candidate.left_grant_id
    other = grant_by_id[other_id]
    return {
        "grant_id": other_id,
        "source_slug": _source_slug(other),
        "title": clean_text(other.title),
        "score": str(candidate.score),
        "duplicate": candidate.duplicate,
        "reasons": list(candidate.reasons),
    }


def _choose_primary(grants: list[Grant]) -> Grant:
    return max(grants, key=_primary_key)


def _primary_key(grant: Grant) -> tuple[int, int, int, int, Decimal, int, float, str]:
    evaluation = evaluate_grant_quality_contract(grant)
    tier_priority = {
        GrantQualityTier.MATCH_READY: 50,
        GrantQualityTier.USABLE_WITH_WARNINGS: 40,
        GrantQualityTier.NEEDS_REVIEW: 20,
        GrantQualityTier.NOISE_REJECTED: 0,
    }[evaluation.tier]
    source_priority = {
        SourceFamily.STRUCTURED_DIRECT: 50,
        SourceFamily.USEFUL_INCOMPLETE: 35,
        SourceFamily.AGGREGATOR: 25,
        SourceFamily.DIGEST_HEAVY: 15,
        SourceFamily.EMPTY_OR_PROBLEM: 5,
        SourceFamily.UNKNOWN: 10,
    }[evaluation.source_family]
    status_priority = {"open": 30, "unknown": 10, "closed": 0}.get(grant.status or "unknown", 0)
    structured_score = sum(
        1
        for value in (
            grant.deadline_at,
            grant.deadline_text,
            grant.funding_amount_text,
            grant.currency,
            grant.funder_name,
            grant.application_url,
            grant.eligibility_text,
        )
        if value
    )
    confidence = Decimal(str(grant.extraction_confidence or 0)).quantize(Decimal("0.0001"))
    text_length = len(" ".join(part for part in (grant.summary, grant.description_text, grant.eligibility_text) if part))
    updated_ts = _timestamp(grant.updated_at)
    return (tier_priority, source_priority, status_priority, structured_score, confidence, text_length, updated_ts, str(grant.id))


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    return value.timestamp()


def _group_id(grant_ids: list[str]) -> str:
    digest = hashlib.sha1("|".join(sorted(grant_ids)).encode("utf-8")).hexdigest()[:12]
    return f"dup-{digest}"


def _url_keys(grant: Grant) -> set[str]:
    keys: set[str] = set()
    for value in (grant.source_url, grant.application_url):
        canonical = canonicalize_url(clean_text(value))
        if canonical and canonical.startswith("http"):
            keys.add(canonical)
    return keys


def _normalized_title(value: str | None) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    lowered = re.sub(r"\([^)]{1,80}\)", " ", lowered)
    lowered = re.sub(r"[^0-9a-zа-яіїєґ]+", " ", lowered)
    tokens = [
        token
        for token in lowered.split()
        if token
        and token
        not in {
            "the",
            "a",
            "an",
            "and",
            "or",
            "for",
            "of",
            "to",
            "in",
            "on",
            "with",
            "grant",
            "grants",
            "funding",
            "support",
            "programme",
            "program",
            "call",
            "open",
            "для",
            "та",
            "і",
            "у",
            "в",
            "на",
            "до",
            "грант",
            "гранти",
            "грантів",
            "конкурс",
            "програма",
            "підтримка",
        }
    ]
    return " ".join(tokens)


def _title_similarity(left: str, right: str) -> Decimal:
    if not left or not right:
        return Decimal("0.0000")
    sequence_ratio = Decimal(str(SequenceMatcher(None, left, right).ratio()))
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return sequence_ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    jaccard = Decimal(len(left_tokens & right_tokens)) / Decimal(len(left_tokens | right_tokens))
    return max(sequence_ratio, jaccard).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _has_meaningful_title(left: str, right: str) -> bool:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    return bool(left_tokens & right_tokens)


def _same_deadline(left: Grant, right: Grant) -> bool:
    if left.deadline_at is not None and right.deadline_at is not None:
        return left.deadline_at.date() == right.deadline_at.date()
    return _same_clean_text(left.deadline_text, right.deadline_text)


def _same_clean_text(left: str | None, right: str | None) -> bool:
    left_cleaned = clean_text(left)
    right_cleaned = clean_text(right)
    return bool(left_cleaned and right_cleaned and left_cleaned.lower() == right_cleaned.lower())


def _same_amount(left: Grant, right: Grant) -> bool:
    if left.currency and right.currency and left.currency != right.currency:
        return False
    if left.funding_amount_max is not None and right.funding_amount_max is not None:
        return Decimal(str(left.funding_amount_max)) == Decimal(str(right.funding_amount_max))
    return _same_clean_text(left.funding_amount_text, right.funding_amount_text)


def _taxonomy_overlap(left: Grant, right: Grant) -> list[str]:
    values: set[str] = set()
    for field_name in ("countries", "regions", "topics", "applicant_types"):
        left_values = {value.lower() for value in getattr(left, field_name, None) or [] if clean_text(value)}
        right_values = {value.lower() for value in getattr(right, field_name, None) or [] if clean_text(value)}
        values.update(left_values & right_values)
    return sorted(values)


def _source_slug(grant: Grant) -> str | None:
    source = getattr(grant, "source", None)
    return clean_text(getattr(source, "slug", None))
