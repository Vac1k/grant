from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from grant_tool.dashboard.service import DashboardService
from grant_tool.db.session import get_session


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["dashboard"])


def get_dashboard(session: Session = Depends(get_session)) -> DashboardService:
    return DashboardService(session)


def _decimal_filter(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError):
        return None


@router.get("/", response_class=HTMLResponse)
def overview(request: Request, dashboard: DashboardService = Depends(get_dashboard)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard/overview.html",
        {
            "active_page": "overview",
            "stats": dashboard.stats(),
            "status_counts": dashboard.status_counts(),
            "source_counts": dashboard.source_counts(),
            "recent_grants": dashboard.recent_grants(limit=8),
            "top_matches_by_client": dashboard.top_matches_by_client(limit_per_client=2),
            "latest_jobs": dashboard.latest_jobs(limit=8),
        },
    )


@router.get("/grants", response_class=HTMLResponse)
def grants(
    request: Request,
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    q: str | None = Query(default=None),
    manual_review: bool | None = Query(default=None),
    quality: str | None = Query(default=None),
    dashboard: DashboardService = Depends(get_dashboard),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard/grants.html",
        {
            "active_page": "grants",
            "stats": dashboard.stats(),
            "grants": dashboard.grants(
                source_slug=source,
                status=status,
                topic=topic,
                q=q,
                manual_review=manual_review,
                quality=quality,
                limit=120,
            ),
            "sources": dashboard.source_options(),
            "topics": dashboard.topic_options(),
            "filters": {
                "source": source,
                "status": status,
                "topic": topic,
                "q": q,
                "manual_review": manual_review,
                "quality": quality,
            },
        },
    )


@router.get("/clients", response_class=HTMLResponse)
def clients(request: Request, dashboard: DashboardService = Depends(get_dashboard)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard/clients.html",
        {
            "active_page": "clients",
            "stats": dashboard.stats(),
            "clients": dashboard.clients(),
        },
    )


@router.get("/matches", response_class=HTMLResponse)
def matches(
    request: Request,
    client: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    dashboard: DashboardService = Depends(get_dashboard),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard/matches.html",
        {
            "active_page": "matches",
            "stats": dashboard.stats(),
            "matches": dashboard.matches(
                client_slug=client,
                min_score=_decimal_filter(min_score),
                limit=150,
            ),
            "clients": dashboard.clients(),
            "filters": {
                "client": client,
                "min_score": min_score,
            },
        },
    )


@router.get("/report", response_class=HTMLResponse)
def report(request: Request, dashboard: DashboardService = Depends(get_dashboard)) -> HTMLResponse:
    context = dashboard.report_context()
    context["active_page"] = "report"
    return templates.TemplateResponse(request, "dashboard/report.html", context)
