from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Iterable

from bs4 import BeautifulSoup

from grant_tool.ingestion.utils import absolute_url, clean_text


def unique_urls(urls: Iterable[str | None], *, limit: int) -> list[str]:
    result: list[str] = []
    for url in urls:
        if not url or url in result:
            continue
        result.append(url)
        if len(result) >= limit:
            break
    return result


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text.encode("utf-8"))


def parse_sitemap_urls(xml_text: str, *, contains: str, limit: int) -> list[str]:
    root = parse_xml(xml_text)
    urls: list[str] = []
    for element in root.iter():
        if element.tag.lower().endswith("loc"):
            text = clean_text(element.text)
            if text and contains in text:
                urls.append(text)
    return unique_urls(urls, limit=limit)


def extract_filtered_links(
    *,
    base_url: str,
    html: str,
    include: str,
    exclude_exact: set[str] | None = None,
    limit: int,
) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    for node in soup.select("a[href]"):
        url = absolute_url(base_url, node.get("href"))
        title = clean_text(node.get_text(" ", strip=True))
        if not url or include not in url or url in seen:
            continue
        if exclude_exact and url.rstrip("/") in {item.rstrip("/") for item in exclude_exact}:
            continue
        if not title or len(title) < 4:
            continue
        seen.add(url)
        links.append((url, title))
        if len(links) >= limit:
            break
    return links
