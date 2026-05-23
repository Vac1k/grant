from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from grant_tool.ingestion.base import BaseConnector
from grant_tool.ingestion.connectors.common import extract_filtered_links
from grant_tool.ingestion.hash import content_hash
from grant_tool.ingestion.types import (
    DiscoveredGrantItemDraft,
    DiscoveryMode,
    FetchedDetail,
    FetchedGrant,
    NormalizedGrantDraft,
)
from grant_tool.ingestion.utils import (
    canonicalize_url,
    clean_text,
    extract_deadline,
    extract_documents,
    extract_funding_text,
    soup_text,
    status_from_deadline,
)


class CloudflareProtectedError(Exception):
    """Raised when Cloudflare protection is detected."""
    pass


class GurtConnector(BaseConnector):
    source_slug = "gurt"
    
    # Cloudflare detection patterns
    CF_PATTERNS = [
        "cf-browser-verification",
        "cloudflare",
        "attention required",
        "enable cookies",
        "browser check",
        "ddos protection",
    ]
    
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._setup_robust_session()

    def _setup_robust_session(self) -> None:
        """Setup session with retries and proper headers."""
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.http.mount("http://", adapter)
        self.http.mount("https://", adapter)
        
        # Standard browser headers (not for bypass, just being polite)
        self.http.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk,ru,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
    
    def _check_cloudflare_block(self, response: requests.Response) -> bool:
        """Detect if Cloudflare is blocking the request."""
        # Check by status code
        if response.status_code == 403:
            return True
        
        # Check by HTML content patterns
        if response.text:
            response_lower = response.text.lower()
            for pattern in self.CF_PATTERNS:
                if pattern in response_lower:
                    return True
        return False
    
    def _fetch_with_fallback(self, url: str) -> requests.Response:
        """
        Fetch URL with proper error handling.
        For research purposes, raises CloudflareProtectedError.
        """
        try:
            response = self.http.get(url, timeout=30)
            
            if self._check_cloudflare_block(response):
                raise CloudflareProtectedError(
                    f"Cloudflare protection detected for {url}. "
                    f"Status: {response.status_code}. "
                    f"Consider: 1) Use official API 2) Manual import 3) Contact site owner"
                )
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to fetch {url}: {e}")
            raise

    def discover(self, *, limit: int, mode: DiscoveryMode) -> list[DiscoveredGrantItemDraft]:
        """
        Discover grants from GURT.
        Falls back to sitemap if available, then to HTML parsing.
        """
        if not self.source.list_url:
            raise ValueError("Source list_url is not configured")
        
        # Try sitemap first (most stable)
        sitemap_url = urljoin(self.source.base_url, "sitemap.xml")
        try:
            links = self._discover_from_sitemap(sitemap_url, limit)
            if links:
                self.logger.info(f"Discovered {len(links)} grants from sitemap")
                return self._create_discovered_items(links, source_type="sitemap")
        except Exception as e:
            self.logger.warning(f"Sitemap discovery failed: {e}, falling back to HTML")
        
        # Fallback to HTML parsing
        response = self._fetch_with_fallback(self.source.list_url)
        links = extract_filtered_links(
            base_url=self.source.base_url,
            html=response.text,
            include="/news/grants/",
            exclude_exact={self.source.list_url},
            limit=limit,
        )
        
        self.logger.info(f"Discovered {len(links)} grants from HTML listing")
        return self._create_discovered_items(links, source_type="html")
    
    def _discover_from_sitemap(self, sitemap_url: str, limit: int) -> list[tuple[str, str]]:
        """Extract grant URLs from sitemap.xml."""
        response = self._fetch_with_fallback(sitemap_url)
        
        # Check if it's an XML sitemap or sitemap index
        if "sitemapindex" in response.text.lower():
            # Parse sitemap index
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)
            namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            
            links = []
            for sitemap in root.findall(".//ns:loc", namespace):
                sub_sitemap_url = sitemap.text
                if "/grants/" in sub_sitemap_url:
                    links.extend(self._discover_from_sitemap(sub_sitemap_url, limit))
                    if len(links) >= limit:
                        break
            return links[:limit]
        else:
            # Parse regular sitemap
            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)
            namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            
            links = []
            for url_elem in root.findall(".//ns:url", namespace):
                loc = url_elem.find("ns:loc", namespace)
                if loc is not None and "/news/grants/" in loc.text:
                    title_elem = url_elem.find("ns:title", namespace)
                    title = title_elem.text if title_elem is not None else loc.text.split("/")[-2]
                    links.append((loc.text, title))
                    if len(links) >= limit:
                        break
            return links
    
    def _create_discovered_items(
        self, 
        links: list[tuple[str, str]], 
        source_type: str
    ) -> list[DiscoveredGrantItemDraft]:
        """Create DiscoveredGrantItemDraft objects from links."""
        return [
            DiscoveredGrantItemDraft(
                source_url=source_url,
                canonical_url=canonicalize_url(source_url),
                source_record_id=source_url,
                title_hint=title_hint,
                listing_url=self.source.list_url,
                listing_position=position,
                content_hash=content_hash({"source_url": source_url, "title_hint": title_hint}),
                discovery_metadata={
                    "listing_url": self.source.list_url,
                    "source_type": source_type,
                },
            )
            for position, (source_url, title_hint) in enumerate(links, start=1)
        ]

    def fetch_detail(self, item: DiscoveredGrantItemDraft) -> FetchedDetail:
        """Fetch individual grant detail page."""
        detail = self._fetch_with_fallback(item.source_url)
        
        return FetchedDetail(
            source_url=item.source_url,
            raw_html=detail.text,
            http_status=detail.status_code,
            content_type=detail.content_type,
            metadata={"source": self.source_slug, "detail_url": item.source_url},
        )

    def normalize(self, item: DiscoveredGrantItemDraft, detail: FetchedDetail) -> NormalizedGrantDraft:
        """Normalize fetched detail into standard format."""
        if not detail.raw_html:
            raise ValueError("GURT detail does not contain HTML")
        return self._parse_detail(
            source_url=item.source_url,
            title_hint=item.title_hint or "Untitled GURT grant",
            detail_html=detail.raw_html,
            http_status=detail.http_status or 200,
            content_type=detail.content_type,
        ).normalized

    def _parse_detail(
        self,
        *,
        source_url: str,
        title_hint: str,
        detail_html: str,
        http_status: int,
        content_type: str | None,
    ) -> FetchedGrant:
        """Parse HTML and extract grant information."""
        text = soup_text(detail_html)
        title = self._extract_title(detail_html) or title_hint
        
        # Enhanced extraction for dates
        deadline_at, deadline_text = self._extract_deadline_robust(detail_html, text)
        
        normalized = NormalizedGrantDraft(
            source_url=source_url,
            source_record_id=source_url,
            title=title,
            summary=self._summary(text),
            description_text=text,
            language="uk",
            deadline_at=deadline_at,
            deadline_text=deadline_text,
            status=status_from_deadline(deadline_at),
            opportunity_type="grant",
            support_type="grant",
            funding_amount_text=extract_funding_text(text),
            documents=extract_documents(self.source.base_url, detail_html),
            source_metadata={"detail_url": source_url},
            extraction_metadata={"connector": self.source_slug},
        )
        return FetchedGrant(
            normalized=normalized,
            raw_html=detail_html,
            raw_text=text,
            raw_title=title,
            raw_summary=normalized.summary,
            http_status=http_status,
            content_type=content_type,
            snapshot_metadata={"source": self.source_slug, "detail_url": source_url},
        )

    def _extract_deadline_robust(self, html: str, text: str) -> tuple[str | None, str | None]:
        """Extract deadline with Ukrainian date formats."""
        from bs4 import BeautifulSoup
        import re
        from datetime import datetime
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Try to find deadline in specific elements first
        deadline_selectors = [
            ".deadline",
            ".grant-deadline",
            "[class*='deadline']",
            "[class*='date']",
            "time",
            ".date",
        ]
        
        for selector in deadline_selectors:
            elements = soup.select(selector)
            for elem in elements:
                elem_text = clean_text(elem.get_text(" ", strip=True))
                if any(word in elem_text.lower() for word in ["deadline", "кінець", "завершення", "до"]):
                    return extract_deadline(elem_text)
        
        # Fallback to full text
        return extract_deadline(text)

    @staticmethod
    def _extract_title(html: str) -> str | None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for selector in ("h1", ".page-title", ".grant-title", "h2", "title"):
            node = soup.select_one(selector)
            if node:
                title = clean_text(node.get_text(" ", strip=True))
                if title and len(title) > 3:  # Avoid empty or too short titles
                    return title
        return None

    @staticmethod
    def _summary(text: str | None) -> str | None:
        if not text:
            return None
        return clean_text(text[:500])

