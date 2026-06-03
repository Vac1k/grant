from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from grant_tool.ingestion.types import NormalizedGrantDraft
from grant_tool.ingestion.utils import clean_text, extract_deadline, status_from_deadline


NORMALIZATION_RULE_VERSION = "data-preparation-step4-v1"


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    changed_fields: tuple[str, ...]
    review_reasons: tuple[str, ...]


_CURRENCY_ALIASES: tuple[tuple[str, str], ...] = (
    ("EUR", "EUR"),
    ("EURO", "EUR"),
    ("ЄВРО", "EUR"),
    ("€", "EUR"),
    ("C$", "CAD"),
    ("CAD", "CAD"),
    ("CANADIAN DOLLAR", "CAD"),
    ("USD", "USD"),
    ("US DOLLAR", "USD"),
    ("DOLLAR", "USD"),
    ("ДОЛАР", "USD"),
    ("ДОЛ.", "USD"),
    ("$", "USD"),
    ("UAH", "UAH"),
    ("ГРН", "UAH"),
    ("ГРИВ", "UAH"),
    ("₴", "UAH"),
    ("GBP", "GBP"),
    ("POUND", "GBP"),
    ("ФУНТ", "GBP"),
    ("£", "GBP"),
    ("PLN", "PLN"),
    ("ZLOTY", "PLN"),
    ("ЗЛОТ", "PLN"),
)

_SOURCE_FUNDER_FALLBACKS = {
    "eu-funding": "European Commission",
    "diia-business": "Diia Business",
}

_UKRAINE_REGION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Vinnytsia", ("вінниць", "vinnytsia")),
    ("Volyn", ("волин", "volyn")),
    ("Dnipropetrovsk", ("дніпр", "dnipro", "dnipropetrovsk")),
    ("Donetsk", ("донець", "donetsk")),
    ("Zhytomyr", ("житомир", "zhytomyr")),
    ("Zakarpattia", ("закарпат", "uzhhorod", "transcarpath")),
    ("Zaporizhzhia", ("запоріз", "zaporizh")),
    ("Ivano-Frankivsk", ("івано-франків", "ivano-frankivsk")),
    ("Kyiv", ("київ", "kyiv", "kiev")),
    ("Kirovohrad", ("кіровоград", "кропивниць", "kirovohrad", "kropyvnyts")),
    ("Luhansk", ("лугансь", "luhansk")),
    ("Lviv", ("львів", "lviv")),
    ("Mykolaiv", ("миколаїв", "mykolaiv")),
    ("Odesa", ("одес", "odesa", "odessa")),
    ("Poltava", ("полтав", "poltava")),
    ("Rivne", ("рівнен", "rivne")),
    ("Sumy", ("сумсь", "sumy")),
    ("Ternopil", ("терноп", "ternopil")),
    ("Kharkiv", ("харків", "kharkiv")),
    ("Kherson", ("херсон", "kherson")),
    ("Khmelnytskyi", ("хмельниць", "khmelnyts")),
    ("Cherkasy", ("черкас", "cherkasy")),
    ("Chernivtsi", ("чернів", "chernivtsi")),
    ("Chernihiv", ("черніг", "chernihiv")),
)


def normalize_grant_draft(
    draft: NormalizedGrantDraft,
    *,
    source_slug: str | None,
    text: str,
    fields: dict[str, Any],
) -> NormalizationResult:
    changed: list[str] = []
    review_reasons: list[str] = []

    _normalize_status(draft, fields, changed)
    _normalize_deadline(draft, text, fields, changed)
    _normalize_funding_and_currency(draft, fields, changed, review_reasons)
    _normalize_geography(draft, text, fields, changed)
    _normalize_funder(draft, source_slug=source_slug, fields=fields, changed=changed)
    _normalize_support_type(draft, text, fields, changed)
    _normalize_eligibility(draft, fields, changed)

    metadata = dict(draft.extraction_metadata or {})
    metadata["normalization_rule_version"] = NORMALIZATION_RULE_VERSION
    if changed:
        metadata["normalized_fields"] = sorted(set([*metadata.get("normalized_fields", []), *changed]))
    draft.extraction_metadata = metadata
    return NormalizationResult(
        changed_fields=tuple(dict.fromkeys(changed)),
        review_reasons=tuple(dict.fromkeys(review_reasons)),
    )


def normalize_currency(value: str | None) -> str | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    upper = cleaned.upper()
    for token, code in _CURRENCY_ALIASES:
        if token in upper:
            return code
    return None


def clean_funding_amount_text(value: str | None) -> str | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    if cleaned.startswith("{") and ("budgetTopicActionMap" in cleaned or "deadlineDates" in cleaned):
        return None
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:funding|budget|grant amount|сума|бюджет|фінансування)\s*[:\-–]\s*", "", cleaned)
    cleaned = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"\b20\d{2}[./-]\d{1,2}[./-]\d{1,2}\b", " ", cleaned)
    cleaned = clean_text(cleaned)
    if not cleaned:
        return None
    if re.fullmatch(r"(?i)(?:eur|euro|євро|usd|дол\.?|uah|gbp|pounds?|фунт|pln|zloty|злот|cad|c\$|€|\$|£|₴|грн)?\s*20\d{2}\s*(?:eur|euro|євро|usd|дол\.?|uah|gbp|pounds?|фунт|pln|zloty|злот|cad|c\$|€|\$|£|₴|грн)?", cleaned):
        return None
    return cleaned[:300]


def normalize_support_type(value: str | None, *, text: str = "") -> str | None:
    cleaned = clean_text(value)
    lowered = f" {cleaned or ''} {text} ".lower()
    if any(token in lowered for token in ("training", "тренінг", "тренинг", "курс", "семінар", "workshop")):
        return "training"
    if any(token in lowered for token in ("tender", "procurement", "тендер", "закупів")):
        return "procurement"
    if any(token in lowered for token in ("loan", "credit", "кредит")):
        return "loan"
    if any(token in lowered for token in ("guarantee", "гарант")):
        return "guarantee"
    if any(token in lowered for token in ("leasing", "лізинг")):
        return "leasing"
    if any(token in lowered for token in ("voucher", "ваучер")):
        return "voucher"
    if any(token in lowered for token in ("compensation", "reimbursement", "компенсац", "відшкодуван")):
        return "compensation"
    if any(token in lowered for token in ("grant", "грант", "call for proposals", "конкурс грант")):
        return "grant"
    if any(token in lowered for token in ("finance programme", "finance program", "фінансова програма", "фінансова підтримка")):
        return "finance_programme"
    return cleaned


def _normalize_status(draft: NormalizedGrantDraft, fields: dict[str, Any], changed: list[str]) -> None:
    original = draft.status
    lowered = (clean_text(draft.status) or "").lower()
    if draft.deadline_at is not None:
        draft.status = status_from_deadline(draft.deadline_at)
    elif any(token in lowered for token in ("open", "active", "ongoing", "forthcoming", "upcoming", "відкрит", "актив", "трива")):
        draft.status = "open"
    elif any(token in lowered for token in ("closed", "expired", "archived", "закрит", "заверш", "архів")):
        draft.status = "closed"
    else:
        draft.status = "unknown"
    if draft.status != original:
        changed.append("status")
        _set_field_evidence(fields, "status_normalized", "deterministic", Decimal("0.82"), f"{original!r} -> {draft.status!r}")


def _normalize_deadline(
    draft: NormalizedGrantDraft,
    text: str,
    fields: dict[str, Any],
    changed: list[str],
) -> None:
    original_text = draft.deadline_text
    if draft.deadline_text:
        draft.deadline_text = _clean_deadline_text(draft.deadline_text)
        if draft.deadline_text != original_text:
            changed.append("deadline_text")
            _set_field_evidence(fields, "deadline_text_normalized", "deterministic", Decimal("0.78"), draft.deadline_text)
    if draft.deadline_at is None:
        deadline_at, deadline_text = extract_deadline(" ".join(part for part in (draft.deadline_text, text) if part))
        if deadline_at is not None:
            draft.deadline_at = deadline_at
            draft.deadline_text = draft.deadline_text or _clean_deadline_text(deadline_text)
            draft.status = status_from_deadline(deadline_at)
            changed.extend(["deadline_at", "status"])
            _set_field_evidence(fields, "deadline_at", "deterministic", Decimal("0.82"), draft.deadline_text or deadline_at.isoformat())


def _clean_deadline_text(value: str | None) -> str | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"(?i)\s*(add to google calendar|google calendar|зафіксувати у google календарі).*", "", cleaned)
    cleaned = re.sub(r"(?i)\s*(share|поділитися|детальніше).*$", "", cleaned)
    return clean_text(cleaned[:240])


def _normalize_funding_and_currency(
    draft: NormalizedGrantDraft,
    fields: dict[str, Any],
    changed: list[str],
    review_reasons: list[str],
) -> None:
    original_text = draft.funding_amount_text
    cleaned_amount = clean_funding_amount_text(draft.funding_amount_text)
    if cleaned_amount != original_text:
        draft.funding_amount_text = cleaned_amount
        changed.append("funding_amount_text")
        _set_field_evidence(fields, "funding_amount_text_normalized", "deterministic", Decimal("0.76"), cleaned_amount or original_text)

    original_currency = draft.currency
    currency = normalize_currency(draft.currency) or normalize_currency(draft.funding_amount_text)
    if currency:
        draft.currency = currency
    elif draft.funding_amount_text:
        review_reasons.append("funding amount has no reliable currency")
    if draft.currency != original_currency:
        changed.append("currency")
        _set_field_evidence(fields, "currency_normalized", "deterministic", Decimal("0.80"), f"{original_currency!r} -> {draft.currency!r}")


def _normalize_geography(
    draft: NormalizedGrantDraft,
    text: str,
    fields: dict[str, Any],
    changed: list[str],
) -> None:
    haystack = f" {draft.geography_text or ''} {text} ".lower()
    original_countries = list(draft.countries or [])
    original_regions = list(draft.regions or [])
    countries = list(draft.countries or [])
    regions = [region for region in draft.regions or [] if clean_text(region)]

    if any(token in haystack for token in ("ukraine", "ukrainian", "україн", "україна", "україни", "вся україна")):
        countries = _merge_list(countries, ["Ukraine"])
    if any(token in haystack for token in ("european union", " eu ", "єс", "європейськ")):
        countries = _merge_list(countries, ["EU"])

    for region, patterns in _UKRAINE_REGION_PATTERNS:
        if any(pattern in haystack for pattern in patterns):
            regions = _merge_list(regions, [region])
    if any(token in haystack for token in ("вся україна", "all ukraine", "nationwide")):
        regions = _merge_list(regions, ["All Ukraine"])

    draft.countries = _merge_list([], countries)
    draft.regions = _merge_list([], regions)
    if draft.countries != original_countries:
        changed.append("countries")
        _set_field_evidence(fields, "countries_normalized", "deterministic", Decimal("0.72"), "; ".join(draft.countries))
    if draft.regions != original_regions:
        changed.append("regions")
        _set_field_evidence(fields, "regions_normalized", "deterministic", Decimal("0.68"), "; ".join(draft.regions))


def _normalize_funder(
    draft: NormalizedGrantDraft,
    *,
    source_slug: str | None,
    fields: dict[str, Any],
    changed: list[str],
) -> None:
    original = draft.funder_name
    draft.funder_name = clean_text(draft.funder_name)
    if not draft.funder_name:
        fallback = _SOURCE_FUNDER_FALLBACKS.get(source_slug or "")
        if fallback:
            draft.funder_name = fallback
        else:
            draft.funder_name = _funder_from_title(draft.title)
    if draft.funder_name != original:
        changed.append("funder_name")
        _set_field_evidence(fields, "funder_name_normalized", "deterministic", Decimal("0.60"), draft.funder_name or original)


def _funder_from_title(title: str | None) -> str | None:
    cleaned = clean_text(title)
    if not cleaned:
        return None
    parenthetical = re.findall(r"\(([^()]{2,80})\)", cleaned)
    for item in reversed(parenthetical):
        candidate = clean_text(item)
        if not candidate:
            continue
        lowered = candidate.lower()
        if any(token in lowered for token in ("grant", "грант", "202", "до ")):
            continue
        if re.search(r"[A-ZА-ЯІЇЄҐ]{2,}", candidate) or len(candidate.split()) <= 5:
            return candidate
    return None


def _normalize_support_type(
    draft: NormalizedGrantDraft,
    text: str,
    fields: dict[str, Any],
    changed: list[str],
) -> None:
    original_support = draft.support_type
    original_opportunity = draft.opportunity_type
    normalized = normalize_support_type(draft.support_type, text=f"{draft.title} {draft.summary or ''} {text[:1000]}")
    if normalized:
        draft.support_type = normalized
    if draft.support_type == "training":
        draft.opportunity_type = "training"
    elif draft.support_type == "procurement":
        draft.opportunity_type = "tender"
    elif draft.support_type in {"loan", "guarantee", "leasing", "voucher", "compensation", "finance_programme"}:
        draft.opportunity_type = "business_support"
    elif draft.support_type == "grant":
        draft.opportunity_type = "grant"
    if draft.support_type != original_support:
        changed.append("support_type")
        _set_field_evidence(fields, "support_type_normalized", "deterministic", Decimal("0.72"), f"{original_support!r} -> {draft.support_type!r}")
    if draft.opportunity_type != original_opportunity:
        changed.append("opportunity_type")
        _set_field_evidence(fields, "opportunity_type_normalized", "deterministic", Decimal("0.72"), f"{original_opportunity!r} -> {draft.opportunity_type!r}")


def _normalize_eligibility(
    draft: NormalizedGrantDraft,
    fields: dict[str, Any],
    changed: list[str],
) -> None:
    original = draft.eligibility_text
    cleaned = _clean_eligibility_text(draft.eligibility_text)
    if cleaned != original:
        draft.eligibility_text = cleaned
        changed.append("eligibility_text")
        _set_field_evidence(fields, "eligibility_text_normalized", "deterministic", Decimal("0.70"), cleaned or original)


def _clean_eligibility_text(value: str | None) -> str | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"(?i)\s*(share|поділитися|детальніше|read more).*$", "", cleaned)
    cleaned = re.sub(r"(?i)\s*(контакти|contact)[^.!?]{0,180}$", "", cleaned)
    return clean_text(cleaned[:900])


def _merge_list(existing: list[str], additions: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *additions]:
        cleaned = clean_text(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


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
