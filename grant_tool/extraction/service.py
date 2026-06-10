from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import unquote, urlparse

from grant_tool.config import get_settings
from grant_tool.data_quality import apply_grant_quality_score, normalize_grant_draft
from grant_tool.db.models import Grant, JobRun, JobType
from grant_tool.db.repositories import GrantRepository
from grant_tool.ingestion.types import FetchedGrant, NormalizedGrantDraft
from grant_tool.ingestion.utils import clean_text, extract_deadline, extract_funding_text, parse_datetime, status_from_deadline


NORMALIZATION_VERSION = "stage5-deterministic-v2"
LLM_EXTRACTION_VERSION = "data-preparation-step6-v1"
LLM_MIN_CONFIDENCE = Decimal("0.5500")
LLM_ALLOWED_CLASSIFICATIONS = {
    "grant",
    "business_support",
    "finance_program",
    "opportunity",
    "digest",
    "news",
    "article",
    "event",
    "webinar",
    "training",
    "tender",
    "unknown",
}


@dataclass(frozen=True, slots=True)
class LlmFallbackDecision:
    allowed: bool
    reasons: tuple[str, ...]
    skipped_reason: str | None = None


@dataclass(slots=True)
class ExtractionSummary:
    job: JobRun
    processed_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    errors: list[str]


@dataclass(frozen=True, slots=True)
class KeywordRule:
    label: str
    patterns: tuple[str, ...]


APPLICANT_TYPE_RULES = (
    KeywordRule("SME", ("sme", "small and medium", "small business", "medium business", "мсп", "мсб", "малий бізнес", "середній бізнес")),
    KeywordRule("startup", ("startup", "start-up", "стартап", "стартапи", "startups")),
    KeywordRule("company", ("company", "companies", "business", "businesses", "підприєм", "бізнес", "компан", "юридичні особи")),
    KeywordRule("NGO", ("ngo", "non-profit", "nonprofit", "civil society", "громадськ", "огс", "неприбутков", "благодійн")),
    KeywordRule("consortium", ("consortium", "consortia", "консорці", "партнерств", "partners", "eu partners")),
)

TOPIC_RULES = (
    KeywordRule("AI", (" ai ", "artificial intelligence", "machine learning", "ml ", "llm", "generative ai", "нейромереж", "штучн", "шi", "ші", "машинн")),
    KeywordRule("defence", ("defence", "defense", "military", "security and defence", "оборон", "військ", "безпек")),
    KeywordRule("dual-use", ("dual-use", "dual use", "подвійн", "подвійного призначення")),
    KeywordRule("innovation", ("innovation", "innovative", "r&d", "research and innovation", "інновац", "дослідж", "технолог")),
    KeywordRule("community", ("community", "communities", "local community", "local communities", "громад", "місцев", "територіальн")),
    KeywordRule("business support", ("business support", "entrepreneurship", "sme", "small business", "підприємниц", "мсп", "мсб")),
    KeywordRule("education", ("education", "educational", "training", "course", "освіт", "навчан", "тренінг", "курс")),
    KeywordRule("culture", ("culture", "creative", "cultural", "культур", "креатив")),
    KeywordRule("humanitarian", ("humanitarian", "human rights", "displaced", "veteran", "relief", "гуманітар", "впо", "ветеран", "постраждал", "захист")),
)

COUNTRY_RULES = {
    "Ukraine": ("ukraine", "ukrainian", "україн", "україна", "україни"),
    "EU": ("european union", " eu ", "єс", "європейськ"),
    "Poland": ("poland", "польщ"),
    "Germany": ("germany", "німеччин"),
    "Moldova": ("moldova", "молд"),
    "Georgia": ("georgia", "грузі"),
    "Belarus": ("belarus", "білорус"),
}

GENERIC_TITLES = {
    "дія бізнес",
    "diia business",
    "вхід",
    "login",
    "untitled diia business programme",
    "untitled opportunity",
}

GENERIC_TOPICS = {
    "grant",
    "grants",
    "грант",
    "гранти",
    "finance",
    "financing",
    "фінанси",
    "фінансування",
    "державна підтримка",
    "підтримка",
    "business",
    "бізнес",
}


class FeatureExtractionService:
    def __init__(
        self,
        *,
        repository: GrantRepository | None = None,
        use_llm: bool = False,
        llm_client: Any | None = None,
    ) -> None:
        self.repository = repository
        self.use_llm = use_llm
        self.llm_client = llm_client

    def enrich_fetched_grant(self, fetched_grant: FetchedGrant, *, source_slug: str | None = None) -> FetchedGrant:
        self.enrich_draft(
            fetched_grant.normalized,
            source_slug=source_slug,
            raw_text=fetched_grant.raw_text,
            raw_html=fetched_grant.raw_html,
            raw_payload=fetched_grant.raw_payload,
        )
        fetched_grant.raw_title = fetched_grant.raw_title or fetched_grant.normalized.title
        fetched_grant.raw_summary = fetched_grant.raw_summary or fetched_grant.normalized.summary
        return fetched_grant

    def enrich_draft(
        self,
        draft: NormalizedGrantDraft,
        *,
        source_slug: str | None = None,
        raw_text: str | None = None,
        raw_html: str | None = None,
        raw_payload: dict[str, Any] | list[Any] | None = None,
    ) -> NormalizedGrantDraft:
        metadata = dict(draft.extraction_metadata or {})
        fields = dict(metadata.get("fields") or {})
        text = self._combined_text(draft, raw_text=raw_text, raw_html=raw_html, raw_payload=raw_payload)
        content_text = self._content_text(draft, raw_text=raw_text)

        original_title = draft.title
        draft.title = self._normalize_title(draft.title, draft.source_url)
        self._set_field_evidence(fields, "title", "deterministic", Decimal("0.90"), draft.title)
        if self._is_generic_title(original_title) and draft.title != original_title:
            self._set_field_evidence(fields, "title_from_url", "deterministic", Decimal("0.60"), draft.source_url)

        if not draft.summary or len(draft.summary) < 80:
            summary = self._build_summary(text)
            if summary:
                draft.summary = summary
                self._set_field_evidence(fields, "summary", "deterministic", Decimal("0.65"), summary)

        if draft.deadline_at is None:
            deadline_at, deadline_text = self._deadline_from_payload(raw_payload)
            if deadline_at is None:
                deadline_at, deadline_text = extract_deadline(text)
            if deadline_at is not None:
                draft.deadline_at = deadline_at
                draft.deadline_text = draft.deadline_text or deadline_text
                self._set_field_evidence(fields, "deadline_at", "deterministic", Decimal("0.85"), deadline_text or deadline_at.isoformat())
        elif draft.deadline_text:
            self._set_field_evidence(fields, "deadline_at", "deterministic", Decimal("0.90"), draft.deadline_text)

        draft.status = self._normalize_status(draft.status, draft.deadline_at)
        self._set_field_evidence(fields, "status", "deterministic", Decimal("0.80"), draft.status)
        if source_slug == "diia-business":
            self._normalize_diia_status(draft, content_text, fields)

        if source_slug == "eu-funding":
            self._normalize_eu_program(draft, fields)

        self._extract_funding(draft, text, fields, raw_payload=raw_payload, source_slug=source_slug)
        self._classify_opportunity(draft, content_text, fields)
        self._extract_taxonomy(draft, content_text, fields)
        self._extract_geography(draft, content_text, fields)
        self._extract_text_features(draft, content_text, fields)
        normalization = normalize_grant_draft(draft, source_slug=source_slug, text=content_text, fields=fields)
        metadata = dict(draft.extraction_metadata or metadata)
        llm_applied = False

        if self.use_llm:
            decision = self._llm_fallback_decision(draft, content_text)
            llm_applied = self._apply_llm_extraction(draft, text, fields, fallback_decision=decision)
            if llm_applied:
                normalization = normalize_grant_draft(draft, source_slug=source_slug, text=content_text, fields=fields)
            metadata = dict(draft.extraction_metadata or metadata)

        confidence = self._confidence(draft, text)
        draft.extraction_confidence = confidence
        if self._needs_manual_review(draft, text):
            draft.needs_manual_review = True
            draft.manual_review_reason = draft.manual_review_reason or self._manual_review_reason(draft, text)
        if normalization.review_reasons and not draft.needs_manual_review:
            draft.needs_manual_review = True
            draft.manual_review_reason = "; ".join(normalization.review_reasons)

        metadata.update(
            {
                "stage": "stage_5",
                "normalization_version": NORMALIZATION_VERSION,
                "data_preparation_normalization_version": draft.extraction_metadata.get("normalization_rule_version"),
                "source_slug": source_slug,
                "fields": fields,
                "feature_card": self._feature_card(draft),
            }
        )
        draft.extraction_metadata = metadata
        return draft

    def run_existing(
        self,
        *,
        source_slug: str | None = None,
        limit: int = 100,
        use_llm: bool | None = None,
    ) -> ExtractionSummary:
        if self.repository is None:
            raise ValueError("FeatureExtractionService.run_existing requires a repository")
        effective_use_llm = self.use_llm if use_llm is None else use_llm
        original_use_llm = self.use_llm
        self.use_llm = effective_use_llm
        job = self.repository.start_job(
            job_type=JobType.FEATURE_EXTRACTION,
            job_metadata={"source_slug": source_slug, "limit": limit, "use_llm": effective_use_llm},
        )
        errors: list[str] = []
        updated = 0
        failed = 0
        grants = self.repository.list_grants_for_feature_extraction(source_slug=source_slug, limit=limit)

        try:
            for grant in grants:
                try:
                    draft = self._draft_from_grant(grant)
                    grant_source_slug = grant.source.slug if grant.source else source_slug
                    self._reset_recomputed_fields(draft, source_slug=grant_source_slug)
                    raw_snapshot = grant.latest_raw_snapshot
                    self.enrich_draft(
                        draft,
                        source_slug=grant_source_slug,
                        raw_text=raw_snapshot.raw_text if raw_snapshot else None,
                        raw_html=raw_snapshot.raw_html if raw_snapshot else None,
                        raw_payload=raw_snapshot.raw_payload if raw_snapshot else None,
                    )
                    self.repository.update_grant_features(
                        grant,
                        title=draft.title,
                        status=draft.status,
                        **draft.to_grant_fields(),
                    )
                    apply_grant_quality_score(grant)
                    self.repository.increment_job_counters(job, processed=1, updated=1)
                    updated += 1
                except Exception as exc:
                    failed += 1
                    errors.append(f"{grant.id}: {exc}")
                    self.repository.increment_job_counters(job, processed=1, failed=1)

            if errors:
                self.repository.mark_job_partial(
                    job,
                    error_message=f"{len(errors)} feature extraction errors",
                    job_metadata={"errors": errors[:20]},
                )
            else:
                self.repository.finish_job_success(job)
        finally:
            self.use_llm = original_use_llm

        return ExtractionSummary(
            job=job,
            processed_count=len(grants),
            updated_count=updated,
            skipped_count=0,
            failed_count=failed,
            errors=errors,
        )

    def _apply_llm_extraction(
        self,
        draft: NormalizedGrantDraft,
        text: str,
        fields: dict[str, Any],
        *,
        fallback_decision: LlmFallbackDecision,
    ) -> bool:
        metadata = dict(draft.extraction_metadata or {})
        if not fallback_decision.allowed:
            metadata["llm"] = {
                "status": "skipped",
                "version": LLM_EXTRACTION_VERSION,
                "reason": fallback_decision.skipped_reason or "deterministic extraction sufficient",
                "fallback_reasons": list(fallback_decision.reasons),
            }
            draft.extraction_metadata = metadata
            return False

        settings = get_settings()
        if self.llm_client is None and not settings.openai_api_key:
            reason = "OPENAI_API_KEY is not configured"
            metadata["llm"] = {
                "status": "skipped",
                "version": LLM_EXTRACTION_VERSION,
                "reason": reason,
                "fallback_reasons": list(fallback_decision.reasons),
            }
            draft.extraction_metadata = metadata
            draft.needs_manual_review = True
            draft.manual_review_reason = FeatureExtractionService._append_review_reason(
                draft.manual_review_reason,
                f"AI fallback skipped: {reason}",
            )
            return False

        client = self.llm_client or OpenAIExtractionClient(api_key=settings.openai_api_key or "", model=settings.llm_model)
        try:
            result = client.extract(draft=draft, text=text)
        except Exception as exc:
            metadata["llm"] = {
                "status": "error",
                "version": LLM_EXTRACTION_VERSION,
                "reason": str(exc),
                "fallback_reasons": list(fallback_decision.reasons),
            }
            draft.extraction_metadata = metadata
            draft.needs_manual_review = True
            draft.manual_review_reason = FeatureExtractionService._append_review_reason(
                draft.manual_review_reason,
                "AI fallback error",
            )
            return False

        validated, schema_errors = self._validate_llm_result(result)
        result_metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        if schema_errors:
            metadata["llm"] = {
                "status": "invalid",
                "version": LLM_EXTRACTION_VERSION,
                "provider": result_metadata.get("provider"),
                "model": result_metadata.get("model"),
                "schema_errors": schema_errors,
                "fallback_reasons": list(fallback_decision.reasons),
                "output": validated,
            }
            draft.extraction_metadata = metadata
            draft.needs_manual_review = True
            draft.manual_review_reason = FeatureExtractionService._append_review_reason(
                draft.manual_review_reason,
                f"AI fallback invalid: {'; '.join(schema_errors[:3])}",
            )
            return False

        confidence = self._decimal(validated.get("confidence"), default=Decimal("0.0000"))
        if confidence < LLM_MIN_CONFIDENCE:
            metadata["llm"] = {
                "status": "low_confidence",
                "version": LLM_EXTRACTION_VERSION,
                "provider": result_metadata.get("provider"),
                "model": result_metadata.get("model"),
                "confidence": str(confidence),
                "fallback_reasons": list(fallback_decision.reasons),
                "output": validated,
            }
            draft.extraction_metadata = metadata
            draft.needs_manual_review = True
            draft.manual_review_reason = FeatureExtractionService._append_review_reason(
                draft.manual_review_reason,
                f"AI fallback low confidence: {confidence}",
            )
            return False

        applied_fields = self._merge_llm_result(draft, validated, fields, metadata)
        metadata["llm"] = {
            "status": "success",
            "version": LLM_EXTRACTION_VERSION,
            "provider": result_metadata.get("provider"),
            "model": result_metadata.get("model"),
            "confidence": str(confidence),
            "fallback_reasons": list(fallback_decision.reasons),
            "applied_fields": applied_fields,
            "output": validated,
        }
        draft.extraction_metadata = metadata
        return bool(applied_fields)

    @staticmethod
    def _llm_fallback_decision(draft: NormalizedGrantDraft, text: str) -> LlmFallbackDecision:
        reasons: list[str] = []
        if len(text) < 80:
            return LlmFallbackDecision(
                allowed=False,
                reasons=(),
                skipped_reason="insufficient source text for AI fallback",
            )
        if not draft.summary or len(draft.summary) < 80:
            reasons.append("weak_summary")
        if not draft.eligibility_text:
            reasons.append("missing_eligibility")
        if not draft.applicant_types:
            reasons.append("missing_applicant_types")
        if not draft.topics:
            reasons.append("missing_topics")
        if not (draft.countries or draft.regions or draft.geography_text):
            reasons.append("missing_geography")
        if FeatureExtractionService._needs_manual_review(draft, text):
            reasons.append("manual_review_risk")
        if not reasons:
            return LlmFallbackDecision(
                allowed=False,
                reasons=(),
                skipped_reason="deterministic extraction sufficient",
            )
        return LlmFallbackDecision(allowed=True, reasons=tuple(dict.fromkeys(reasons)))

    @staticmethod
    def _validate_llm_result(result: Any) -> tuple[dict[str, Any], list[str]]:
        errors: list[str] = []
        if not isinstance(result, dict):
            return {}, ["result must be a JSON object"]

        validated: dict[str, Any] = {}
        for name in ("summary", "eligibility_text", "restrictions_text"):
            value = result.get(name)
            if value is None:
                continue
            cleaned = clean_text(str(value))
            if cleaned:
                validated[name] = cleaned[:1200]

        for name in ("applicant_types", "topics", "countries", "regions"):
            value = result.get(name)
            if value is None:
                continue
            if not isinstance(value, list):
                errors.append(f"{name} must be a list")
                continue
            cleaned_values = []
            for item in value[:12]:
                cleaned = clean_text(str(item))
                if cleaned and cleaned not in cleaned_values:
                    cleaned_values.append(cleaned[:80])
            validated[name] = cleaned_values

        classification = clean_text(result.get("classification"))
        if classification:
            classification = classification.lower().replace("-", "_").replace(" ", "_")
            if classification not in LLM_ALLOWED_CLASSIFICATIONS:
                errors.append("classification is not allowed")
            else:
                validated["classification"] = classification

        confidence = FeatureExtractionService._decimal(result.get("confidence"), default=Decimal("-1"))
        if confidence < Decimal("0.0000") or confidence > Decimal("1.0000"):
            errors.append("confidence must be a number between 0 and 1")
        else:
            validated["confidence"] = str(confidence)

        evidence = result.get("evidence")
        if evidence is not None:
            if not isinstance(evidence, dict):
                errors.append("evidence must be an object")
            else:
                validated["evidence"] = {
                    str(key)[:80]: clean_text(str(value))[:500]
                    for key, value in evidence.items()
                    if clean_text(str(value))
                }

        supported_fields = set(validated) - {"confidence", "evidence"}
        if not supported_fields:
            errors.append("result has no supported extraction fields")
        return validated, errors

    @staticmethod
    def _merge_llm_result(
        draft: NormalizedGrantDraft,
        result: dict[str, Any],
        fields: dict[str, Any],
        metadata: dict[str, Any],
    ) -> list[str]:
        applied_fields: list[str] = []
        confidence = FeatureExtractionService._decimal(result.get("confidence"), default=Decimal("0.65"))
        text_field_rules = {
            "summary": lambda current: not current or len(current) < 80,
            "eligibility_text": lambda current: not current,
            "restrictions_text": lambda current: not current,
        }
        for name, can_apply in text_field_rules.items():
            value = clean_text(result.get(name))
            current = getattr(draft, name)
            if value and can_apply(current):
                setattr(draft, name, value)
                applied_fields.append(name)
                FeatureExtractionService._set_field_evidence(
                    fields,
                    name,
                    "llm",
                    confidence,
                    value,
                )
        for name in ("applicant_types", "topics", "countries", "regions"):
            values = result.get(name)
            if isinstance(values, list):
                before = list(getattr(draft, name) or [])
                merged = FeatureExtractionService._merge_list(before, [clean_text(str(value)) for value in values])
                cleaned = [value for value in merged if value]
                if cleaned != before:
                    setattr(draft, name, cleaned)
                    applied_fields.append(name)
                    FeatureExtractionService._set_field_evidence(
                        fields,
                        name,
                        "llm",
                        confidence,
                        "; ".join(cleaned),
                    )
        classification = clean_text(result.get("classification"))
        if classification and classification in LLM_ALLOWED_CLASSIFICATIONS and not metadata.get("classification"):
            metadata["classification"] = classification
            applied_fields.append("classification")
            FeatureExtractionService._set_field_evidence(fields, "classification", "llm", confidence, classification)
        return applied_fields

    @staticmethod
    def _draft_from_grant(grant: Grant) -> NormalizedGrantDraft:
        return NormalizedGrantDraft(
            source_url=grant.source_url,
            source_record_id=grant.source_record_id,
            title=grant.title,
            status=grant.status,
            application_url=grant.application_url,
            summary=grant.summary,
            description_text=grant.description_text,
            published_at=grant.published_at,
            deadline_at=grant.deadline_at,
            deadline_text=grant.deadline_text,
            program_name=grant.program_name,
            funder_name=grant.funder_name,
            opportunity_type=grant.opportunity_type,
            support_type=grant.support_type,
            funding_amount_min=grant.funding_amount_min,
            funding_amount_max=grant.funding_amount_max,
            funding_amount_text=grant.funding_amount_text,
            currency=grant.currency,
            geography_text=grant.geography_text,
            countries=list(grant.countries or []),
            regions=list(grant.regions or []),
            eligibility_text=grant.eligibility_text,
            applicant_types=list(grant.applicant_types or []),
            topics=list(grant.topics or []),
            keywords=list(grant.keywords or []),
            restrictions_text=grant.restrictions_text,
            cofinancing_text=grant.cofinancing_text,
            consortium_text=grant.consortium_text,
            documents=list(grant.documents or []),
            source_metadata=dict(grant.source_metadata or {}),
            extraction_confidence=grant.extraction_confidence,
            extraction_metadata=dict(grant.extraction_metadata or {}),
            needs_manual_review=grant.needs_manual_review,
            manual_review_reason=grant.manual_review_reason,
        )

    @staticmethod
    def _reset_recomputed_fields(draft: NormalizedGrantDraft, *, source_slug: str | None = None) -> None:
        draft.summary = None
        draft.deadline_at = None
        draft.deadline_text = None
        if source_slug == "diia-business":
            draft.opportunity_type = "business_support"
            draft.support_type = "finance_programme"
        else:
            draft.opportunity_type = "grant"
            draft.support_type = "grant"
        draft.funding_amount_min = None
        draft.funding_amount_max = None
        draft.funding_amount_text = None
        draft.currency = None
        draft.geography_text = None
        draft.countries = []
        draft.regions = []
        draft.eligibility_text = None
        draft.applicant_types = []
        draft.topics = []
        draft.keywords = []
        draft.restrictions_text = None
        draft.cofinancing_text = None
        draft.consortium_text = None
        draft.extraction_confidence = None
        draft.extraction_metadata = {}
        draft.needs_manual_review = False
        draft.manual_review_reason = None

    @staticmethod
    def _combined_text(
        draft: NormalizedGrantDraft,
        *,
        raw_text: str | None,
        raw_html: str | None,
        raw_payload: dict[str, Any] | list[Any] | None,
    ) -> str:
        del raw_html
        parts = [
            draft.title,
            draft.summary,
            draft.description_text,
            draft.deadline_text,
            draft.funding_amount_text,
            draft.eligibility_text,
            draft.restrictions_text,
            draft.geography_text,
            raw_text,
            FeatureExtractionService._payload_text(raw_payload),
        ]
        return clean_text(" ".join(part for part in parts if part)) or ""

    @staticmethod
    def _content_text(draft: NormalizedGrantDraft, *, raw_text: str | None) -> str:
        parts = [
            draft.title,
            draft.summary,
            draft.description_text,
            draft.eligibility_text,
            draft.restrictions_text,
            draft.geography_text,
            raw_text if not draft.description_text else None,
        ]
        return clean_text(" ".join(part for part in parts if part)) or ""

    @staticmethod
    def _deadline_from_payload(raw_payload: dict[str, Any] | list[Any] | None) -> tuple[datetime | None, str | None]:
        if raw_payload is None:
            return None, None
        candidates: list[datetime] = []

        def collect_from_text(value: str) -> None:
            if "deadline" not in value.lower():
                return
            for match in re.finditer(r"\b20\d{2}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", value):
                parsed = parse_datetime(match.group(0))
                if parsed:
                    candidates.append(parsed)

        def walk(value: Any, *, key_context: str = "") -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(item, key_context=f"{key_context} {key}".strip())
                return
            if isinstance(value, list | tuple):
                for item in value:
                    walk(item, key_context=key_context)
                return
            if value is None:
                return
            text_value = str(value)
            if "deadline" in key_context.lower():
                parsed = parse_datetime(text_value)
                if parsed:
                    candidates.append(parsed)
            collect_from_text(text_value)

        walk(raw_payload)
        if not candidates:
            return None, None

        now = datetime.now(UTC)
        future = sorted(candidate for candidate in candidates if candidate.date() >= now.date())
        chosen = future[0] if future else max(candidates)
        evidence = "payload deadline dates: " + ", ".join(sorted({candidate.date().isoformat() for candidate in candidates}))
        return chosen, evidence

    @staticmethod
    def _payload_text(raw_payload: dict[str, Any] | list[Any] | None) -> str | None:
        if raw_payload is None:
            return None
        try:
            return json.dumps(raw_payload, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(raw_payload)

    @staticmethod
    def _normalize_title(title: str, source_url: str) -> str:
        cleaned = clean_text(title) or "Untitled opportunity"
        if not FeatureExtractionService._is_generic_title(cleaned):
            return cleaned
        slug_title = FeatureExtractionService._title_from_url(source_url)
        return slug_title or cleaned

    @staticmethod
    def _title_from_url(source_url: str) -> str | None:
        path = unquote(urlparse(source_url).path.rstrip("/"))
        slug = path.rsplit("/", 1)[-1]
        if not slug or slug in {"programs", "finance", "all"}:
            return None
        title = slug.replace("_", " ").replace("-", " ")
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 6:
            return None
        return title[:1].upper() + title[1:]

    @staticmethod
    def _is_generic_title(title: str | None) -> bool:
        normalized = (clean_text(title) or "").lower()
        return normalized in GENERIC_TITLES

    @staticmethod
    def _build_summary(text: str) -> str | None:
        cleaned = clean_text(text)
        if not cleaned:
            return None
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        summary_parts: list[str] = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 25:
                continue
            summary_parts.append(sentence)
            if len(" ".join(summary_parts)) >= 300:
                break
        summary = " ".join(summary_parts) or cleaned[:500]
        return clean_text(summary[:700])

    @staticmethod
    def _normalize_status(status: str | None, deadline_at: datetime | None) -> str:
        lowered = (status or "").lower()
        if deadline_at is not None:
            return status_from_deadline(deadline_at)
        if any(token in lowered for token in ("open", "forthcoming", "upcoming", "ongoing", "відкрит", "active")):
            return "open"
        if any(token in lowered for token in ("closed", "expired", "закрит", "архів")):
            return "closed"
        return "unknown"

    @staticmethod
    def _normalize_diia_status(draft: NormalizedGrantDraft, text: str, fields: dict[str, Any]) -> None:
        if draft.status != "unknown" or draft.deadline_at is not None:
            return
        lowered = f" {text.lower()} "
        explicit_closed_signal = any(
            token in lowered
            for token in (
                "архів",
                "прийом заявок завершено",
                "прийом заявок закрито",
                "програма завершена",
                "програма закрита",
                "неактивна програма",
            )
        )
        if explicit_closed_signal:
            return
        open_ended_signal = any(
            token in lowered
            for token in (
                "постійно",
                "безстрок",
                "до припинення",
                "діє програма",
                "подати заявку",
                "отримати грант",
                "отримати фінансування",
            )
        )
        active_finance_program = draft.support_type in {"grant", "finance_programme", "loan", "guarantee", "leasing", "factoring"}
        active_finance_page = "business.diia.gov.ua/finance" in draft.source_url
        if open_ended_signal or (active_finance_program and (draft.application_url or active_finance_page)):
            draft.status = "open"
            FeatureExtractionService._set_field_evidence(
                fields,
                "status",
                "deterministic",
                Decimal("0.68"),
                "Diia active/open-ended finance programme without explicit deadline",
            )

    @staticmethod
    def _normalize_eu_program(draft: NormalizedGrantDraft, fields: dict[str, Any]) -> None:
        metadata = draft.source_metadata.get("eu_metadata") if isinstance(draft.source_metadata, dict) else None
        if not isinstance(metadata, dict):
            return
        current = draft.program_name or ""
        if current.isdigit() or not current:
            program = FeatureExtractionService._first_payload_text(metadata.get("frameworkProgramme")) or FeatureExtractionService._first_payload_text(metadata.get("programme"))
            if program:
                draft.program_name = program
                FeatureExtractionService._set_field_evidence(fields, "program_name", "deterministic", Decimal("0.85"), program)

    @staticmethod
    def _first_payload_text(value: Any) -> str | None:
        if isinstance(value, list | tuple):
            for item in value:
                text = FeatureExtractionService._first_payload_text(item)
                if text:
                    return text
            return None
        if isinstance(value, dict):
            for key in ("value", "label", "name", "title", "content"):
                text = FeatureExtractionService._first_payload_text(value.get(key))
                if text:
                    return text
            return None
        return clean_text(str(value)) if value is not None else None

    @staticmethod
    def _extract_funding(
        draft: NormalizedGrantDraft,
        text: str,
        fields: dict[str, Any],
        *,
        raw_payload: dict[str, Any] | list[Any] | None = None,
        source_slug: str | None = None,
    ) -> None:
        contextual_snippet = FeatureExtractionService._snippet(
            text,
            ("funding", "budget", "grant amount", "сума", "фінанс", "бюджет", "підтримк"),
            radius=360,
        )
        payload_budget = FeatureExtractionService._budget_context_from_payload(raw_payload)
        source_amount_text = draft.funding_amount_text
        if source_slug == "diia-business" and not source_amount_text:
            source_amount_text = FeatureExtractionService._diia_grant_amount_text(draft.source_metadata, raw_payload)
        source_currency = draft.currency
        if source_slug == "diia-business" and not source_currency:
            source_currency = FeatureExtractionService._diia_currency_text(draft.source_metadata, raw_payload)
        source_amount_context = clean_text(" ".join(part for part in (source_amount_text, source_currency) if part))
        funding_context = clean_text(
            " ".join(
                part
                for part in (
                    source_amount_text,
                    draft.currency,
                    payload_budget or contextual_snippet,
                    None if payload_budget else extract_funding_text(text),
                )
                if part
            )
        )
        amount_min, amount_max, currency = (None, None, None)
        if source_slug == "diia-business" and source_amount_context:
            amount_min, amount_max, currency = FeatureExtractionService._parse_funding(source_amount_context, source_slug=source_slug)
            if amount_min is not None or amount_max is not None:
                funding_context = source_amount_context
        if amount_min is None and amount_max is None and payload_budget:
            amount_min, amount_max, currency = FeatureExtractionService._parse_funding(payload_budget, source_slug=source_slug)
        if amount_min is None and amount_max is None:
            amount_min, amount_max, currency = FeatureExtractionService._parse_funding(funding_context, source_slug=source_slug)
        funding_text = None
        if amount_min is not None or amount_max is not None:
            if payload_budget:
                funding_text = FeatureExtractionService._format_funding_text(amount_min, amount_max, currency or draft.currency)
            elif source_slug == "diia-business" and source_amount_text:
                funding_text = source_amount_text
            else:
                funding_text = extract_funding_text(FeatureExtractionService._strip_dates(funding_context)) or draft.funding_amount_text or contextual_snippet
                if FeatureExtractionService._looks_like_suspicious_funding_text(funding_text):
                    funding_text = None
                funding_text = funding_text or FeatureExtractionService._format_funding_text(amount_min, amount_max, currency or draft.currency)
        elif draft.funding_amount_text and FeatureExtractionService._looks_like_suspicious_funding_text(draft.funding_amount_text):
            FeatureExtractionService._set_field_evidence(
                fields,
                "funding_amount_rejected",
                "deterministic",
                Decimal("0.75"),
                draft.funding_amount_text,
            )
            draft.funding_amount_text = None
        if funding_text and (
            not draft.funding_amount_text
            or FeatureExtractionService._looks_like_date(draft.funding_amount_text)
            or FeatureExtractionService._looks_like_suspicious_funding_text(draft.funding_amount_text)
        ):
            draft.funding_amount_text = funding_text
        if draft.funding_amount_min is None and amount_min is not None:
            draft.funding_amount_min = amount_min
        if draft.funding_amount_max is None and amount_max is not None:
            draft.funding_amount_max = amount_max
        if draft.currency is None and currency is not None:
            draft.currency = currency
        if funding_text:
            FeatureExtractionService._set_field_evidence(fields, "funding_amount", "deterministic", Decimal("0.70"), funding_text[:300])

    @staticmethod
    def _budget_context_from_payload(raw_payload: dict[str, Any] | list[Any] | None) -> str | None:
        if raw_payload is None:
            return None

        def walk(value: Any, *, key_context: str = "") -> str | None:
            if isinstance(value, dict):
                for key, item in value.items():
                    found = walk(item, key_context=f"{key_context} {key}".strip())
                    if found:
                        return found
                return None
            if isinstance(value, list | tuple):
                for item in value:
                    found = walk(item, key_context=key_context)
                    if found:
                        return found
                return None
            if value is None:
                return None
            text_value = str(value)
            lowered_context = key_context.lower()
            if "budget" in lowered_context and ("budgetTopicActionMap" in text_value or "maxContribution" in text_value):
                return text_value
            return None

        return walk(raw_payload)

    @staticmethod
    def _diia_grant_amount_text(source_metadata: dict[str, Any] | None, raw_payload: dict[str, Any] | list[Any] | None) -> str | None:
        return FeatureExtractionService._diia_attribute_text(source_metadata, raw_payload, keys={"grantamount", "сума"})

    @staticmethod
    def _diia_currency_text(source_metadata: dict[str, Any] | None, raw_payload: dict[str, Any] | list[Any] | None) -> str | None:
        return FeatureExtractionService._diia_attribute_text(source_metadata, raw_payload, keys={"currency", "валюта"})

    @staticmethod
    def _diia_attribute_text(
        source_metadata: dict[str, Any] | None,
        raw_payload: dict[str, Any] | list[Any] | None,
        *,
        keys: set[str],
    ) -> str | None:
        metadata_attributes = source_metadata.get("attributes") if isinstance(source_metadata, dict) else None
        value = FeatureExtractionService._diia_attribute_from_attributes(metadata_attributes, keys=keys)
        if value:
            return value

        def walk(payload: Any) -> str | None:
            if isinstance(payload, dict):
                value = FeatureExtractionService._diia_attribute_from_attributes(payload.get("serviceAttributes"), keys=keys)
                if value:
                    return value
                for item in payload.values():
                    found = walk(item)
                    if found:
                        return found
            elif isinstance(payload, list):
                for item in payload:
                    found = walk(item)
                    if found:
                        return found
            return None

        return walk(raw_payload)

    @staticmethod
    def _diia_attribute_from_attributes(attributes: Any, *, keys: set[str]) -> str | None:
        if not isinstance(attributes, list):
            return None
        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            key = clean_text(attribute.get("key"))
            value = clean_text(attribute.get("value"))
            if not value:
                continue
            if key and FeatureExtractionService._normalise_key(key) in keys:
                return value

            category_attribute = attribute.get("categoryAttribute") if isinstance(attribute.get("categoryAttribute"), dict) else {}
            nested_attribute = category_attribute.get("attribute") if isinstance(category_attribute.get("attribute"), dict) else {}
            names = [
                nested_attribute.get("name"),
                nested_attribute.get("title"),
                *[
                    translation.get("title")
                    for translation in nested_attribute.get("translations", [])
                    if isinstance(translation, dict)
                ],
            ]
            if any(FeatureExtractionService._normalise_key(str(name or "")) in keys for name in names):
                return value
        return None

    @staticmethod
    def _normalise_key(value: str) -> str:
        return re.sub(r"[^a-zа-яіїєґ0-9]+", "", value.lower())

    @staticmethod
    def _classify_opportunity(draft: NormalizedGrantDraft, text: str, fields: dict[str, Any]) -> None:
        title = f" {draft.title} ".lower()
        intro = f" {text[:900]} ".lower()
        training_in_title = any(token in title for token in ("тренінг", "тренинг", "training", "workshop", "семінар"))
        training_intro = re.search(r"(запрошує|реєстрац|набір)[^.]{0,160}(тренінг|тренинг|training|курс|семінар|workshop)", intro)
        grant_in_title = any(token in title for token in ("грант", "конкурс", "запит на подання", "rfa", "request for applications"))
        if training_in_title or (training_intro and not grant_in_title):
            draft.opportunity_type = "training"
            draft.support_type = "training"
            FeatureExtractionService._set_field_evidence(fields, "opportunity_type", "deterministic", Decimal("0.80"), "training/course keyword")
            return
        if any(token in title for token in ("тендер", "tender", "procurement", "закупів")):
            draft.opportunity_type = "tender"
            draft.support_type = "procurement"
            FeatureExtractionService._set_field_evidence(fields, "opportunity_type", "deterministic", Decimal("0.80"), "tender/procurement keyword")

    @staticmethod
    def _strip_dates(text: str | None) -> str | None:
        if text is None:
            return None
        cleaned = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b", " ", text)
        cleaned = re.sub(r"\b20\d{2}[./-]\d{1,2}[./-]\d{1,2}\b", " ", cleaned)
        return clean_text(cleaned)

    @staticmethod
    def _looks_like_date(text: str | None) -> bool:
        cleaned = clean_text(text) or ""
        return bool(
            re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]20\d{2}\.?", cleaned)
            or re.fullmatch(r"20\d{2}[./-]\d{1,2}[./-]\d{1,2}", cleaned)
        )

    @staticmethod
    def _parse_funding(text: str | None, *, source_slug: str | None = None) -> tuple[Decimal | None, Decimal | None, str | None]:
        cleaned = clean_text(text)
        if not cleaned:
            return None, None, None
        json_amounts = FeatureExtractionService._parse_json_funding(cleaned)
        if json_amounts[0] is not None or json_amounts[1] is not None:
            return json_amounts
        if cleaned.strip().startswith("{"):
            return None, None, None

        lowered = cleaned.lower()
        has_money_signal = any(
            token in lowered
            for token in (
                "eur",
                "euro",
                "€",
                "cad",
                "c$",
                "canadian dollar",
                "usd",
                "$",
                "gbp",
                "£",
                "pound",
                "pln",
                "zlot",
                "uah",
                "грн",
                "₴",
                "євро",
                "дол",
                "фунт",
                "funding",
                "budget",
                "grant amount",
                "фінанс",
                "бюджет",
                "сума",
            )
        )
        if not has_money_signal:
            return None, None, None

        currency = None
        if "€" in lowered or re.search(r"\b(?:eur|euro)\b", lowered):
            currency = "EUR"
        elif "євро" in lowered:
            currency = "EUR"
        elif "c$" in lowered or re.search(r"\bcad\b", lowered) or "canadian dollar" in lowered:
            currency = "CAD"
        elif "$" in lowered or re.search(r"\busd\b", lowered) or "дол" in lowered:
            currency = "USD"
        elif "£" in lowered or re.search(r"\bgbp\b", lowered) or "pound" in lowered or "фунт" in lowered:
            currency = "GBP"
        elif re.search(r"\bpln\b", lowered) or "zlot" in lowered or "злот" in lowered:
            currency = "PLN"
        elif "₴" in lowered or "грн" in lowered or re.search(r"\buah\b", lowered):
            currency = "UAH"

        amount_source = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b", " ", cleaned)
        amount_source = re.sub(r"\b20\d{2}[./-]\d{1,2}[./-]\d{1,2}\b", " ", amount_source)
        amount_matches = re.finditer(
            r"(?P<prefix>€|eur|euro|євро|usd|дол\.?|gbp|£|pounds?|фунт|pln|zloty|злот|cad|c\$|uah|\$|грн|₴)?\s*(?P<number>\d[\d\s.,]*)(?:\s*(?P<multiplier>k|m|тис\.?|млн\.?|million|thousand))?(?:\s*(?P<suffix>€|eur|euro|євро|usd|дол\.?|gbp|£|pounds?|фунт|pln|zloty|злот|cad|c\$|uah|\$|грн|₴))?",
            amount_source,
            flags=re.IGNORECASE,
        )
        amounts: list[Decimal] = []
        for match in amount_matches:
            number = match.group("number")
            multiplier = match.group("multiplier")
            amount = FeatureExtractionService._number_to_decimal(number, multiplier)
            if amount is None:
                continue
            window_start = max(0, match.start() - 40)
            window_end = min(len(amount_source), match.end() + 40)
            window = amount_source[window_start:window_end]
            if not FeatureExtractionService._valid_funding_amount_candidate(
                number=number,
                multiplier=multiplier,
                amount=amount,
                window=window,
                source_slug=source_slug,
            ):
                continue
            amounts.append(amount)
        if not amounts:
            return None, None, currency
        if currency is None and max(amounts) < Decimal("10000"):
            return None, None, None
        if any(token in lowered for token in ("up to", "до ", "максим", "max")):
            return None, max(amounts), currency
        if len(amounts) >= 2:
            return min(amounts), max(amounts), currency
        return amounts[0], amounts[0], currency

    @staticmethod
    def _valid_funding_amount_candidate(
        *,
        number: str,
        multiplier: str | None,
        amount: Decimal,
        window: str,
        source_slug: str | None,
    ) -> bool:
        if FeatureExtractionService._looks_like_classification_number(number, window):
            return False
        if re.search(r"(?<!\d)20\d{2}(?!\d)", number.strip(" .,")):
            return False
        compact = number.replace(" ", "").strip(".,")
        if re.fullmatch(r"20\d{2}", compact):
            return False
        lowered_window = window.lower()
        has_adjacent_currency = bool(re.search(r"(€|c\$|\$|£|₴|\beur\b|\beuro\b|євро|\busd\b|дол|\bgbp\b|pounds?|фунт|\bpln\b|zloty|злот|\bcad\b|canadian dollar|\buah\b|грн)", lowered_window))
        has_money_word = any(token in lowered_window for token in ("funding", "budget", "grant amount", "сума", "фінанс", "бюджет", "підтримк"))
        if multiplier:
            return True
        if source_slug == "eu-funding":
            return has_adjacent_currency
        if has_adjacent_currency:
            return True
        return has_money_word and amount >= Decimal("10000")

    @staticmethod
    def _looks_like_classification_number(number: str, window: str) -> bool:
        compact = number.replace(" ", "").strip(".,")
        if re.fullmatch(r"\d{1,2}[.,]\d{1,2}", compact):
            lowered_window = window.lower()
            has_adjacent_currency = bool(re.search(r"(€|c\$|\$|£|₴|\beur\b|\beuro\b|євро|\busd\b|дол|\bgbp\b|pounds?|фунт|\bpln\b|zloty|злот|\bcad\b|canadian dollar|\buah\b|грн)", lowered_window))
            if compact.startswith("0") or not has_adjacent_currency or any(token in lowered_window for token in ("квед", "nace", "classification", "класиф")):
                return True
        return False

    @staticmethod
    def _looks_like_suspicious_funding_text(text: str | None) -> bool:
        cleaned = clean_text(text) or ""
        if not cleaned:
            return False
        if cleaned.startswith("{") and ("budgetTopicActionMap" in cleaned or "deadlineDates" in cleaned):
            return True
        if re.fullmatch(r"(?i)(?:eur|euro|євро|usd|дол\.?|gbp|pounds?|фунт|pln|zloty|злот|cad|c\$|uah|€|\$|£|₴|грн)?\s*20\d{2}\s*(?:eur|euro|євро|usd|дол\.?|gbp|pounds?|фунт|pln|zloty|злот|cad|c\$|uah|€|\$|£|₴|грн)?", cleaned):
            return True
        return FeatureExtractionService._looks_like_classification_number(cleaned, cleaned)

    @staticmethod
    def _format_funding_text(amount_min: Decimal | None, amount_max: Decimal | None, currency: str | None) -> str | None:
        if amount_min is None and amount_max is None:
            return None
        prefix = f"{currency} " if currency else ""
        if amount_min is not None and amount_max is not None and amount_min != amount_max:
            return f"{prefix}{FeatureExtractionService._format_amount(amount_min)} - {FeatureExtractionService._format_amount(amount_max)}"
        amount = amount_max if amount_max is not None else amount_min
        return f"{prefix}{FeatureExtractionService._format_amount(amount)}" if amount is not None else None

    @staticmethod
    def _format_amount(amount: Decimal) -> str:
        normalized = amount.quantize(Decimal("1")) if amount == amount.to_integral() else amount.normalize()
        return f"{normalized:,}".replace(",", " ")

    @staticmethod
    def _parse_json_funding(text: str) -> tuple[Decimal | None, Decimal | None, str | None]:
        if not text.strip().startswith("{"):
            return None, None, None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None, None, None
        values: list[Decimal] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"minContribution", "maxContribution"}:
                        amount = FeatureExtractionService._number_to_decimal(str(item), None)
                        if amount is not None and amount > 0:
                            values.append(amount)
                    else:
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(payload)
        if not values:
            return None, None, "EUR"
        return min(values), max(values), "EUR"

    @staticmethod
    def _number_to_decimal(value: str, multiplier: str | None) -> Decimal | None:
        compact = value.replace(" ", "").strip(".,")
        if "," in compact and "." in compact:
            if compact.rfind(".") > compact.rfind(","):
                normalized = compact.replace(",", "")
            else:
                normalized = compact.replace(".", "").replace(",", ".")
        elif "," in compact:
            if re.fullmatch(r"\d{1,3}(,\d{3})+", compact):
                normalized = compact.replace(",", "")
            else:
                normalized = compact.replace(",", ".")
        elif "." in compact:
            if re.fullmatch(r"\d{1,3}(\.\d{3})+", compact):
                normalized = compact.replace(".", "")
            else:
                normalized = compact
        else:
            normalized = compact
        try:
            amount = Decimal(normalized)
        except Exception:
            return None
        multiplier = (multiplier or "").lower()
        if multiplier in {"k", "тис", "тис.", "thousand"}:
            amount *= Decimal("1000")
        elif multiplier in {"m", "млн", "млн.", "million"}:
            amount *= Decimal("1000000")
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _extract_taxonomy(draft: NormalizedGrantDraft, text: str, fields: dict[str, Any]) -> None:
        draft.topics = FeatureExtractionService._remove_generic_topics(draft.topics)
        applicant_types = FeatureExtractionService._match_rules(text, APPLICANT_TYPE_RULES)
        topics = FeatureExtractionService._match_rules(text, TOPIC_RULES)
        if applicant_types:
            draft.applicant_types = FeatureExtractionService._merge_list(draft.applicant_types, applicant_types)
            FeatureExtractionService._set_field_evidence(fields, "applicant_types", "deterministic", Decimal("0.70"), "; ".join(applicant_types))
        if topics:
            draft.topics = FeatureExtractionService._merge_list(draft.topics, topics)
            FeatureExtractionService._set_field_evidence(fields, "topics", "deterministic", Decimal("0.70"), "; ".join(topics))
        draft.keywords = FeatureExtractionService._merge_list(draft.keywords, draft.topics)

    @staticmethod
    def _remove_generic_topics(topics: list[str] | None) -> list[str]:
        cleaned_topics: list[str] = []
        for topic in topics or []:
            cleaned = clean_text(topic)
            if not cleaned:
                continue
            normalized = cleaned.lower()
            if normalized in GENERIC_TOPICS:
                continue
            cleaned_topics.append(cleaned)
        return FeatureExtractionService._merge_list([], cleaned_topics)

    @staticmethod
    def _match_rules(text: str, rules: tuple[KeywordRule, ...]) -> list[str]:
        padded = f" {text.lower()} "
        matches: list[str] = []
        for rule in rules:
            if any(pattern in padded for pattern in rule.patterns):
                matches.append(rule.label)
        return matches

    @staticmethod
    def _extract_geography(draft: NormalizedGrantDraft, text: str, fields: dict[str, Any]) -> None:
        padded = f" {text.lower()} "
        countries = [country for country, patterns in COUNTRY_RULES.items() if any(pattern in padded for pattern in patterns)]
        if countries:
            draft.countries = FeatureExtractionService._merge_list(draft.countries, countries)
            snippet = FeatureExtractionService._snippet(text, ("ukraine", "україн", "єс", "european union", "eu"))
            draft.geography_text = draft.geography_text or snippet
            FeatureExtractionService._set_field_evidence(fields, "countries", "deterministic", Decimal("0.70"), snippet or "; ".join(countries))

    @staticmethod
    def _extract_text_features(draft: NormalizedGrantDraft, text: str, fields: dict[str, Any]) -> None:
        eligibility = FeatureExtractionService._snippet(
            text,
            (
                "eligible",
                "eligibility",
                "who can apply",
                "applicants",
                "для кого",
                "хто може",
                "до участі",
                "заявники",
                "учасник",
                "підприєм",
                "огс",
            ),
        )
        if eligibility and not draft.eligibility_text:
            draft.eligibility_text = eligibility
            FeatureExtractionService._set_field_evidence(fields, "eligibility_text", "deterministic", Decimal("0.62"), eligibility)

        restrictions = FeatureExtractionService._snippet(
            text,
            ("not eligible", "not allowed", "restriction", "excluded", "не можуть", "не допуска", "обмеж", "виключ"),
        )
        if restrictions and not draft.restrictions_text:
            draft.restrictions_text = restrictions
            FeatureExtractionService._set_field_evidence(fields, "restrictions_text", "deterministic", Decimal("0.58"), restrictions)

        cofinancing = FeatureExtractionService._snippet(text, ("cofinancing", "co-financing", "co funding", "co-funding", "співфінанс"))
        if cofinancing and not draft.cofinancing_text:
            draft.cofinancing_text = cofinancing
            FeatureExtractionService._set_field_evidence(fields, "cofinancing_text", "deterministic", Decimal("0.70"), cofinancing)

        consortium = FeatureExtractionService._snippet(text, ("consortium", "consortia", "консорці", "партнер"))
        if consortium and not draft.consortium_text:
            draft.consortium_text = consortium
            FeatureExtractionService._set_field_evidence(fields, "consortium_text", "deterministic", Decimal("0.70"), consortium)

    @staticmethod
    def _snippet(text: str, keywords: tuple[str, ...], *, radius: int = 240) -> str | None:
        lowered = text.lower()
        indexes = [lowered.find(keyword.lower()) for keyword in keywords]
        indexes = [index for index in indexes if index >= 0]
        if not indexes:
            return None
        index = min(indexes)
        start = max(0, index - radius // 2)
        end = min(len(text), index + radius)
        return clean_text(text[start:end])

    @staticmethod
    def _merge_list(existing: list[str] | None, additions: list[str | None]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in [*(existing or []), *additions]:
            cleaned = clean_text(value)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result

    @staticmethod
    def _confidence(draft: NormalizedGrantDraft, text: str) -> Decimal:
        score = Decimal("0.20")
        if draft.title and not FeatureExtractionService._is_generic_title(draft.title):
            score += Decimal("0.12")
        if len(text) > 250:
            score += Decimal("0.12")
        if draft.summary:
            score += Decimal("0.08")
        if draft.deadline_at:
            score += Decimal("0.10")
        if draft.funding_amount_text or draft.funding_amount_max:
            score += Decimal("0.08")
        if draft.applicant_types:
            score += Decimal("0.10")
        if draft.topics:
            score += Decimal("0.10")
        if draft.eligibility_text:
            score += Decimal("0.07")
        if draft.restrictions_text or draft.cofinancing_text or draft.consortium_text:
            score += Decimal("0.03")
        return min(score, Decimal("0.95")).quantize(Decimal("0.0001"))

    @staticmethod
    def _needs_manual_review(draft: NormalizedGrantDraft, text: str) -> bool:
        return FeatureExtractionService._is_generic_title(draft.title) or len(text) < 80 or (not draft.topics and not draft.applicant_types)

    @staticmethod
    def _manual_review_reason(draft: NormalizedGrantDraft, text: str) -> str:
        reasons: list[str] = []
        if FeatureExtractionService._is_generic_title(draft.title):
            reasons.append("generic title")
        if len(text) < 80:
            reasons.append("very short extracted text")
        if not draft.topics and not draft.applicant_types:
            reasons.append("no applicant/topic taxonomy detected")
        return "; ".join(reasons) or "low extraction confidence"

    @staticmethod
    def _append_review_reason(current: str | None, reason: str) -> str:
        reasons = [item.strip() for item in (current or "").split(";") if item.strip()]
        if reason not in reasons:
            reasons.append(reason)
        return "; ".join(reasons)

    @staticmethod
    def _feature_card(draft: NormalizedGrantDraft) -> dict[str, Any]:
        return {
            "title": draft.title,
            "summary": draft.summary,
            "status": draft.status,
            "deadline_at": draft.deadline_at.isoformat() if draft.deadline_at else None,
            "deadline_text": draft.deadline_text,
            "program_name": draft.program_name,
            "funder_name": draft.funder_name,
            "funding_amount_min": str(draft.funding_amount_min) if draft.funding_amount_min is not None else None,
            "funding_amount_max": str(draft.funding_amount_max) if draft.funding_amount_max is not None else None,
            "currency": draft.currency,
            "countries": draft.countries,
            "applicant_types": draft.applicant_types,
            "topics": draft.topics,
            "needs_manual_review": draft.needs_manual_review,
            "manual_review_reason": draft.manual_review_reason,
        }

    @staticmethod
    def _set_field_evidence(
        fields: dict[str, Any],
        name: str,
        method: str,
        confidence: Decimal,
        evidence: str | None,
    ) -> None:
        fields[name] = {
            "method": method,
            "confidence": str(confidence.quantize(Decimal("0.0001"))),
            "evidence": clean_text(evidence)[:500] if evidence else None,
        }

    @staticmethod
    def _decimal(value: Any, *, default: Decimal) -> Decimal:
        try:
            return Decimal(str(value)).quantize(Decimal("0.0001"))
        except Exception:
            return default


class OpenAIExtractionClient:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def extract(self, *, draft: NormalizedGrantDraft, text: str) -> dict[str, Any]:
        import httpx

        prompt = (
            "You are a controlled fallback extractor for grant records. "
            "Extract only facts explicitly supported by the source text. "
            "Do not infer or invent missing fields. "
            "Return compact JSON with this schema: "
            "{summary: string|null, eligibility_text: string|null, restrictions_text: string|null, "
            "applicant_types: string[], topics: string[], countries: string[], regions: string[], "
            "classification: one of grant,business_support,finance_program,opportunity,digest,news,article,event,webinar,training,tender,unknown, "
            "confidence: number between 0 and 1, evidence: object}. "
            "Use empty arrays/null when evidence is missing."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "title": draft.title,
                            "source_url": draft.source_url,
                            "text": text[:12000],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        result["metadata"] = {"status": "success", "provider": "openai", "model": self.model}
        return result
