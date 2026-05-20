from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urljoin

from bs4 import BeautifulSoup


_WHITESPACE_RE = re.compile(r"\s+")
_DATE_PATTERNS = (
    re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b"),
    re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b"),
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
        "приймаються до",
        "до ",
        "кінцевий термін",
    )
    lowered = cleaned.lower()
    for keyword in keywords:
        idx = lowered.find(keyword)
        if idx == -1:
            continue
        snippet = cleaned[idx : idx + 180]
        parsed = parse_datetime(snippet)
        if parsed:
            return parsed, snippet
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
    match = pattern.search(cleaned)
    if match:
        return clean_text(match.group(0))
    return None


def status_from_deadline(deadline_at: datetime | None) -> str:
    if deadline_at is None:
        return "unknown"
    now = datetime.now(UTC)
    return "open" if deadline_at >= now else "closed"
