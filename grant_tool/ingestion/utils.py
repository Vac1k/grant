from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


_WHITESPACE_RE = re.compile(r"\s+")
_DATE_PATTERNS = (
    re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b"),
    re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2})\b"),
    re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b"),
)
_UK_MONTHS = {
    "січня": 1,
    "січень": 1,
    "лютого": 2,
    "лютий": 2,
    "березня": 3,
    "березень": 3,
    "квітня": 4,
    "квітень": 4,
    "травня": 5,
    "травень": 5,
    "червня": 6,
    "червень": 6,
    "липня": 7,
    "липень": 7,
    "серпня": 8,
    "серпень": 8,
    "вересня": 9,
    "вересень": 9,
    "жовтня": 10,
    "жовтень": 10,
    "листопада": 11,
    "листопад": 11,
    "грудня": 12,
    "грудень": 12,
}
_UK_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+("
    + "|".join(sorted(_UK_MONTHS, key=len, reverse=True))
    + r")\s+(20\d{2})\b",
    re.IGNORECASE,
)
_EN_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_EN_MONTH_PATTERN = "|".join(sorted(_EN_MONTHS, key=len, reverse=True))
_EN_DATE_MONTH_FIRST_RE = re.compile(
    rf"\b({_EN_MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(20\d{{2}})\b",
    re.IGNORECASE,
)
_EN_DATE_DAY_FIRST_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_EN_MONTH_PATTERN})\.?[,]?\s+(20\d{{2}})\b",
    re.IGNORECASE,
)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _WHITESPACE_RE.sub(" ", unescape(value)).strip()
    return cleaned or None


def soup_text(html: str, selectors: tuple[str, ...] = ("article", "main", "body")) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if text:
                return text
    return clean_text(soup.get_text(" ", strip=True))


def absolute_url(base_url: str, url: str | None) -> str | None:
    if not url:
        return None
    return urljoin(base_url, url)


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return clean_text(url)

    tracking_prefixes = ("utm_",)
    tracking_keys = {
        "fbclid",
        "gclid",
        "gbraid",
        "wbraid",
        "mc_cid",
        "mc_eid",
        "yclid",
    }
    query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in tracking_keys or any(lowered.startswith(prefix) for prefix in tracking_prefixes):
            continue
        query_pairs.append((key, value))

    query = urlencode(sorted(query_pairs), doseq=True)
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def first_text(values: object) -> str | None:
    if values is None:
        return None
    if isinstance(values, list | tuple):
        for value in values:
            text = first_text(value)
            if text:
                return text
        return None
    if isinstance(values, dict):
        for key in ("value", "label", "name", "title", "content"):
            text = first_text(values.get(key))
            if text:
                return text
        return None
    return clean_text(str(values))


def list_text(values: object) -> list[str]:
    if values is None:
        return []
    if isinstance(values, list | tuple | set):
        result: list[str] = []
        for value in values:
            text = first_text(value)
            if text and text not in result:
                result.append(text)
        return result
    text = first_text(values)
    return [text] if text else []


def parse_datetime(value: str | None) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    uk_match = _UK_DATE_RE.search(text.lower())
    if uk_match:
        day = int(uk_match.group(1))
        month = _UK_MONTHS[uk_match.group(2).lower()]
        year = int(uk_match.group(3))
        try:
            return datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            pass
    en_month_first_match = _EN_DATE_MONTH_FIRST_RE.search(text.lower())
    if en_month_first_match:
        month = _EN_MONTHS[en_month_first_match.group(1).lower()]
        day = int(en_month_first_match.group(2))
        year = int(en_month_first_match.group(3))
        try:
            return datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            pass
    en_day_first_match = _EN_DATE_DAY_FIRST_RE.search(text.lower())
    if en_day_first_match:
        day = int(en_day_first_match.group(1))
        month = _EN_MONTHS[en_day_first_match.group(2).lower()]
        year = int(en_day_first_match.group(3))
        try:
            return datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            pass
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        parts = [int(part) for part in match.groups()]
        if len(str(parts[0])) == 4:
            year, month, day = parts
        else:
            day, month, year = parts
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            continue
    return None


def extract_deadline(text: str | None) -> tuple[datetime | None, str | None]:
    cleaned = clean_text(text)
    if not cleaned:
        return None, None
    keywords = (
        "deadline",
        "дедлайн",
        "актуально до",
        "подати до",
        "подання до",
        "заповнити до",
        "заповніть",
        "приймаються до",
        "кінцевий термін",
        "термін подання",
        "не пізніше",
        "мають бути отримані",
        "заявки мають бути",
    )
    lowered = cleaned.lower()
    for keyword in keywords:
        start = 0
        while True:
            idx = lowered.find(keyword, start)
            if idx == -1:
                break
            snippet = cleaned[idx : idx + 220]
            parsed = parse_datetime(snippet)
            if parsed:
                return parsed, snippet
            start = idx + len(keyword)
    if len(cleaned) <= 240:
        parsed = parse_datetime(cleaned)
        if parsed:
            return parsed, None
    return None, None


def extract_documents(base_url: str, html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    documents: list[dict[str, str]] = []
    for link in soup.select("a[href]"):
        href = link.get("href")
        absolute = absolute_url(base_url, href)
        title = clean_text(link.get_text(" ", strip=True)) or absolute
        if not absolute:
            continue
        lowered = absolute.lower()
        if any(ext in lowered for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")):
            documents.append({"title": title or absolute, "url": absolute})
    return documents


def extract_funding_text(text: str | None) -> str | None:
    cleaned = clean_text(text)
    if not cleaned:
        return None
    pattern = re.compile(
        r"(?i)(?:€|eur|euro|грн|uah|usd|\$)?\s?\d[\d\s.,]{2,}\s?(?:€|eur|euro|грн|uah|usd|\$|тис\.?|млн\.?)?"
    )
    matches = [clean_text(match.group(0)) for match in pattern.finditer(cleaned)]
    markers = ("€", "eur", "euro", "грн", "uah", "usd", "$", "тис", "млн")
    for match in matches:
        if match and any(marker in match.lower() for marker in markers):
            return match
    return next((match for match in matches if match), None)


def status_from_deadline(deadline_at: datetime | None) -> str:
    if deadline_at is None:
        return "unknown"
    now = datetime.now(UTC)
    if deadline_at.hour == 0 and deadline_at.minute == 0 and deadline_at.second == 0:
        return "open" if deadline_at.date() >= now.date() else "closed"
    return "open" if deadline_at >= now else "closed"
