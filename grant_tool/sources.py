from __future__ import annotations

from typing import Any

from grant_tool.db.models import AccessStrategy, JobRun, JobType, Source
from grant_tool.db.repositories import GrantRepository


MVP_SOURCE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "slug": "eu-funding",
        "name": "EU Funding & Tenders Portal",
        "base_url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home",
        "api_url": "https://api.tech.ec.europa.eu/search-api/prod/rest/search",
        "access_strategy": AccessStrategy.API,
        "rate_limit_seconds": 2,
        "notes": "Use the official/API-style EU search endpoint with apiKey=SEDIA where required.",
        "source_metadata": {
            "priority": 1,
            "mvp": True,
            "region_focus": ["EU", "Ukraine"],
        },
    },
    {
        "slug": "prostir",
        "name": "Prostir grants",
        "base_url": "https://www.prostir.ua",
        "list_url": "https://www.prostir.ua/category/grants/",
        "feed_url": "https://www.prostir.ua/category/grants/feed/",
        "access_strategy": AccessStrategy.RSS,
        "rate_limit_seconds": 5,
        "notes": "Use RSS for discovery and HTML detail pages for full text and extraction.",
        "source_metadata": {
            "priority": 2,
            "mvp": True,
            "country_focus": ["Ukraine"],
        },
    },
    {
        "slug": "diia-business",
        "name": "Diia Business finance programs",
        "base_url": "https://www.business.diia.gov.ua",
        "list_url": "https://www.business.diia.gov.ua/finance/programs",
        "sitemap_url": "https://www.business.diia.gov.ua/sitemap.xml",
        "access_strategy": AccessStrategy.SITEMAP_HTML,
        "rate_limit_seconds": 5,
        "notes": "Use sitemap/list pages and SSR HTML details for business finance/support programmes.",
        "source_metadata": {
            "priority": 3,
            "mvp": True,
            "country_focus": ["Ukraine"],
            "includes_non_grant_finance_programmes": True,
        },
    },
    {
        "slug": "gurt",
        "name": "GURT grants",
        "base_url": "https://gurt.org.ua",
        "list_url": "https://gurt.org.ua/news/grants/",
        "access_strategy": AccessStrategy.HTML,
        "rate_limit_seconds": 8,
        "notes": "Use conservative HTML list/detail parsing; important fields may require later LLM extraction.",
        "source_metadata": {
            "priority": 4,
            "mvp": True,
            "country_focus": ["Ukraine"],
        },
    },
)


def seed_mvp_sources(repository: GrantRepository) -> tuple[JobRun, list[Source]]:
    job = repository.start_job(
        job_type=JobType.SEED_SOURCES,
        job_metadata={"source_slugs": [source["slug"] for source in MVP_SOURCE_DEFINITIONS]},
    )
    seeded_sources: list[Source] = []

    try:
        for source_definition in MVP_SOURCE_DEFINITIONS:
            existing = repository.get_source_by_slug(source_definition["slug"])
            source = repository.upsert_source(**source_definition)
            seeded_sources.append(source)
            if existing is None:
                repository.increment_job_counters(job, processed=1, created=1)
            else:
                repository.increment_job_counters(job, processed=1, updated=1)
    except Exception as exc:
        repository.finish_job_failed(job, error_message=str(exc))
        raise

    repository.finish_job_success(job, job_metadata={"seeded_count": len(seeded_sources)})
    return job, seeded_sources
