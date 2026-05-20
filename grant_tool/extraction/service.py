from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import unquote, urlparse

from grant_tool.config import get_settings
from grant_tool.db.models import Grant, JobRun, JobType
from grant_tool.db.repositories import GrantRepository
from grant_tool.ingestion.types import FetchedGrant, NormalizedGrantDraft
from grant_tool.ingestion.utils import clean_text, extract_deadline, extract_funding_text, status_from_deadline


NORMALIZATION_VERSION = "stage5-deterministic-v1"


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
    KeywordRule("community", ("community", "communities", "local", "громад", "місцев", "територіальн")),
    KeywordRule("business support", ("business support", "entrepreneurship", "sme", "small business", "підприємниц", "бізнес", "мсп", "мсб")),
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
            deadline_at, deadline_text = extract_deadline(text)
            if deadline_at is not None:
                draft.deadline_at = deadline_at
                draft.deadline_text = draft.deadline_text or deadline_text
                self._set_field_evidence(fields, "deadline_at", "deterministic", Decimal("0.85"), deadline_text or deadline_at.isoformat())
        elif draft.deadline_text:
            self._set_field_evidence(fields, "deadline_at", "deterministic", Decimal("0.90"), draft.deadline_text)

        draft.status = self._normalize_status(draft.status, draft.deadline_at)
        self._set_field_evidence(fields, "status", "deterministic", Decimal("0.80"), draft.status)

        if source_slug == "eu-funding":
            self._normalize_eu_program(draft, fields)

        self._extract_funding(draft, text, fields)
        self._extract_taxonomy(draft, text, fields)
        self._extract_geography(draft, text, fields)
        self._extract_text_features(draft, text, fields)

        if self.use_llm:
            self._apply_llm_extraction(draft, text, fields)

        confidence = self._confidence(draft, text)
        draft.extraction_confidence = confidence
        draft.extraction_method = "deterministic_llm" if self.use_llm and metadata.get("llm", {}).get("status") == "success" else "deterministic"
        if self._needs_manual_review(draft, text):
            draft.needs_manual_review = True
            draft.manual_review_reason = draft.manual_review_reason or self._manual_review_reason(draft, text)

        metadata.update(
            {
                "stage": "stage_5",
                "normalization_version": NORMALIZATION_VERSION,
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
                    self._reset_recomputed_fields(draft)
                    raw_snapshot = grant.latest_raw_snapshot
                    self.enrich_draft(
                        draft,
                        source_slug=grant.source.slug if grant.source else source_slug,
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
    ) -> None:
        metadata = draft.extraction_metadata or {}
        settings = get_settings()
        if self.llm_client is None and not settings.openai_api_key:
            metadata["llm"] = {"status": "skipped", "reason": "OPENAI_API_KEY is not configured"}
            draft.extraction_metadata = metadata
            return
        client = self.llm_client or OpenAIExtractionClient(api_key=settings.openai_api_key or "", model=settings.llm_model)
        result = client.extract(draft=draft, text=text)
        metadata["llm"] = result.get("metadata", {"status": "success"})
        self._merge_llm_result(draft, result, fields)
        draft.extraction_metadata = metadata

    @staticmethod
    def _merge_llm_result(draft: NormalizedGrantDraft, result: dict[str, Any], fields: dict[str, Any]) -> None:
        for name in ("summary", "eligibility_text", "restrictions_text"):
            value = clean_text(result.get(name))
            if value and not getattr(draft, name):
                setattr(draft, name, value)
                FeatureExtractionService._set_field_evidence(
                    fields,
                    name,
                    "llm",
                    FeatureExtractionService._decimal(result.get("confidence"), default=Decimal("0.65")),
                    value,
                )
        for name in ("applicant_types", "topics"):
            values = result.get(name)
            if isinstance(values, list):
                merged = FeatureExtractionService._merge_list(getattr(draft, name), [clean_text(str(value)) for value in values])
                setattr(draft, name, [value for value in merged if value])
                FeatureExtractionService._set_field_evidence(
                    fields,
                    name,
                    "llm",
                    FeatureExtractionService._decimal(result.get("confidence"), default=Decimal("0.65")),
                    "; ".join(getattr(draft, name)),
                )

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
            language=grant.language,
            published_at=grant.published_at,
            opens_at=grant.opens_at,
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
            cofinancing_required=grant.cofinancing_required,
            cofinancing_text=grant.cofinancing_text,
            consortium_required=grant.consortium_required,
            consortium_text=grant.consortium_text,
            implementation_period_text=grant.implementation_period_text,
            contact_text=grant.contact_text,
            documents=list(grant.documents or []),
            source_metadata=dict(grant.source_metadata or {}),
            extraction_method=grant.extraction_method or "deterministic",
            extraction_confidence=grant.extraction_confidence,
            extraction_metadata=dict(grant.extraction_metadata or {}),
            needs_manual_review=grant.needs_manual_review,
            manual_review_reason=grant.manual_review_reason,
        )

    @staticmethod
    def _reset_recomputed_fields(draft: NormalizedGrantDraft) -> None:
        draft.summary = None
        draft.deadline_at = None
        draft.deadline_text = None
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
        draft.cofinancing_required = None
        draft.cofinancing_text = None
        draft.consortium_required = None
        draft.consortium_text = None
        draft.implementation_period_text = None
        draft.contact_text = None
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
    def _extract_funding(draft: NormalizedGrantDraft, text: str, fields: dict[str, Any]) -> None:
        contextual_snippet = FeatureExtractionService._snippet(
            text,
            ("funding", "budget", "grant amount", "сума", "фінанс", "бюджет", "підтримк"),
            radius=360,
        )
        funding_context = clean_text(" ".join(part for part in (draft.funding_amount_text, contextual_snippet, extract_funding_text(text)) if part))
        funding_text = extract_funding_text(FeatureExtractionService._strip_dates(funding_context)) or draft.funding_amount_text or contextual_snippet
        if funding_text and (not draft.funding_amount_text or FeatureExtractionService._looks_like_date(draft.funding_amount_text)):
            draft.funding_amount_text = funding_text
        amount_min, amount_max, currency = FeatureExtractionService._parse_funding(funding_context)
        if draft.funding_amount_min is None and amount_min is not None:
            draft.funding_amount_min = amount_min
        if draft.funding_amount_max is None and amount_max is not None:
            draft.funding_amount_max = amount_max
        if draft.currency is None and currency is not None:
            draft.currency = currency
        if funding_text:
            FeatureExtractionService._set_field_evidence(fields, "funding_amount", "deterministic", Decimal("0.70"), funding_text[:300])

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
    def _parse_funding(text: str | None) -> tuple[Decimal | None, Decimal | None, str | None]:
        cleaned = clean_text(text)
        if not cleaned:
            return None, None, None
        json_amounts = FeatureExtractionService._parse_json_funding(cleaned)
        if json_amounts[0] is not None or json_amounts[1] is not None:
            return json_amounts

        lowered = cleaned.lower()
        has_money_signal = any(
            token in lowered
            for token in (
                "eur",
                "euro",
                "€",
                "usd",
                "$",
                "uah",
                "грн",
                "₴",
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
        if any(token in lowered for token in ("eur", "euro", "€")):
            currency = "EUR"
        elif any(token in lowered for token in ("usd", "$")):
            currency = "USD"
        elif any(token in lowered for token in ("uah", "грн", "₴")):
            currency = "UAH"

        amount_source = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b", " ", cleaned)
        amount_source = re.sub(r"\b20\d{2}[./-]\d{1,2}[./-]\d{1,2}\b", " ", amount_source)
        amount_matches = re.findall(r"(?:€|eur|euro|usd|uah|\$|грн|₴)?\s*(\d[\d\s.,]*)(?:\s*(k|m|тис\.?|млн\.?|million|thousand))?", amount_source, flags=re.IGNORECASE)
        amounts = [FeatureExtractionService._number_to_decimal(number, multiplier) for number, multiplier in amount_matches]
        amounts = [amount for amount in amounts if amount is not None]
        if not amounts:
            return None, None, currency
        if any(token in lowered for token in ("up to", "до ", "максим", "max")):
            return None, max(amounts), currency
        if len(amounts) >= 2:
            return min(amounts), max(amounts), currency
        return amounts[0], amounts[0], currency

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
        normalized = value.replace(" ", "").replace(",", ".")
        if normalized.count(".") > 1:
            normalized = normalized.replace(".", "")
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
        if cofinancing:
            draft.cofinancing_required = True
            draft.cofinancing_text = draft.cofinancing_text or cofinancing
            FeatureExtractionService._set_field_evidence(fields, "cofinancing_required", "deterministic", Decimal("0.70"), cofinancing)

        consortium = FeatureExtractionService._snippet(text, ("consortium", "consortia", "консорці", "партнер"))
        if consortium:
            draft.consortium_required = True
            draft.consortium_text = draft.consortium_text or consortium
            FeatureExtractionService._set_field_evidence(fields, "consortium_required", "deterministic", Decimal("0.70"), consortium)

        implementation = FeatureExtractionService._snippet(text, ("implementation period", "duration", "тривалість", "період реалізації"))
        if implementation and not draft.implementation_period_text:
            draft.implementation_period_text = implementation

        contact = FeatureExtractionService._snippet(text, ("contact", "email", "e-mail", "@", "контакт"))
        if contact and not draft.contact_text:
            draft.contact_text = contact

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
            "Extract only factual grant fields from the provided source text. "
            "Do not infer facts that are not explicitly supported. "
            "Return compact JSON with keys: summary, eligibility_text, applicant_types, topics, "
            "restrictions_text, confidence, evidence."
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
