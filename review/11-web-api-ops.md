# Web/API, dashboard & deployment/ops

**Assessment: weak.** *Written by direct reading of `grant_tool/main.py`,
`dashboard/routes.py`, `dashboard/service.py`, `api/routes/health.py`, `docker-compose.yml`,
`Dockerfile`, and the ops docs — the reviewer agent for this dimension did not run before the
session token limit. Findings are my own; the headline (no-auth) overlaps [SEC-1](02-security.md),
which **was** independently verified as critical.*

## Summary

The web layer itself is small and clean: a single `create_app()` factory, five read-only dashboard
routes using FastAPI dependency injection (`Depends(get_dashboard)` / `Depends(get_session)`), a
`DashboardService` that does all DB access with `selectinload` (no N+1 on the page loads), Jinja2
templates with autoescaping on, and one health endpoint. As a *read-only internal viewer* the code
quality is fine. The problem is everything around it: **no authentication** over confidential client
data (the critical issue), a `docker-compose.yml` that is dev-only (`--reload`, source bind-mounts,
`grant:grant` creds, exposed Redis/Postgres), **no observability** (no logging — see
[CQ-1](07-code-quality.md)), and a pipeline that is **run by hand** via six CLI commands with no
scheduling (Celery is present but inert — [ARCH-1](06-architecture.md)). This is laptop-grade, not
deployment-grade.

## Strengths

- Clean app factory and route layer; consistent dependency injection; `DashboardService` cleanly separates DB access from routing.
- Dashboard reads use `selectinload` for relationship traversal — no lazy-load N+1 on page loads (`dashboard/service.py:57-146`).
- Jinja2 autoescaping on by default; no `| safe`/`Markup()` — scraped/LLM content is escaped (good, given the untrusted inputs).
- The health endpoint exists and is sensibly mounted under `/api/v1`.
- The dashboard is deliberately read-only ("Dashboard є read-only layer") — it never mutates extraction/matching, which keeps the web surface small and reasoning simple.
- `_decimal_filter` defensively handles bad `min_score` query input.

---

## Findings

### 🔴 WEBOPS-1 — No authentication on the dashboard/API serving client PII — `critical`
**Location:** `main.py:11-24`; `dashboard/routes.py:34-133`
**= [SEC-1](02-security.md), independently verified `critical`.**

See [SEC-1](02-security.md) for the full write-up. From the web angle: every route is an open `GET`
with only `Depends(get_dashboard)`/`Depends(get_session)` — no auth dependency, no middleware, no
`401`/`403` anywhere. `/clients` eager-loads full `ClientProfile` + `ApplicationHistory` (names,
product descriptions, risks, project summaries, notes); `/matches` surfaces client names + scores.
Bound to `0.0.0.0:8000`. **Must be gated before any non-localhost use.** **Effort: medium.**

### 🟡 WEBOPS-2 — Pipeline is run entirely by hand; no scheduling despite Celery being present — `medium`
**Location:** `docs/start.md` smoke flow (6 sequential `docker compose exec` commands); `celery_app.py` (healthcheck only); `dashboard/routes.py` (never triggers a run)

Producing fresh matches requires an operator to manually run `import → ingest → extract → embed →
match → explain` in order, every cycle. Nothing schedules this; the dashboard can't trigger it; the
`worker`/`beat` services run nothing ([ARCH-1](06-architecture.md)). So the data a viewer sees is
only as fresh as the last manual run, and correct ordering depends on operator discipline.

**Why it matters:** An "internal tool" that needs a human to run six commands in sequence to refresh
isn't operable beyond its author. This is the gap between a script collection and a service.

**Recommendation:** Either wire the stages into Celery `beat` (real scheduled pipeline) or provide a
single orchestration command/script with enforced ordering and a `PipelineRun` id
([ARCH-5](06-architecture.md)). Decide Celery's fate ([ARCH-1](06-architecture.md)) first. **Effort: medium.**

### 🟡 WEBOPS-3 — No observability beyond `/health` and DB-buried error strings — `medium`
**Location:** entire web/worker path (no logging — [CQ-1](07-code-quality.md)); `api/routes/health.py` (only signal)

There is no request logging, no metrics, no error tracking, and no structured logs in the web or
(would-be) worker paths. The only runtime signal is `/health`, which returns `status: ok` plus the
app name and environment. A failing dashboard query or a stuck job is invisible.

**Why it matters:** You cannot operate or debug a deployed service you can't see into. Combined with
no auth, there's also no access audit — who viewed which client's data is unknowable.

**Recommendation:** Add structured logging ([CQ-1](07-code-quality.md)) + request logging
middleware; expand health into readiness (DB/Redis reachable) and basic metrics; add an access log
once auth exists. **Effort: small–medium.**

### 🟡 WEBOPS-4 — `docker-compose.yml` is dev-only but is the only deploy artifact — `medium`
**Location:** `docker-compose.yml` (also [SEC-4](02-security.md), [SEC-5](02-security.md))

`--reload`, source bind-mounts, `grant:grant:grant` creds, Postgres on `5432` and Redis on `6379`
published to the host, no resource limits, container runs as root. There is no prod profile. As the
single compose file, it's what a deployer would reach for — shipping dev posture to prod.

**Why it matters:** Reusing this for any shared environment imports every dev shortcut as a
production weakness.

**Recommendation:** Add a separate prod compose/profile (no `--reload`/bind-mounts, secrets-based
creds, non-root, no host-published DB/Redis), document the current file as local-only. **Effort: small.**
(See [SEC-4](02-security.md)/[SEC-5](02-security.md).)

### ⚪ WEBOPS-5 — Dashboard list endpoints fetch-then-filter in Python; no real pagination — `low`
**Location:** `dashboard/service.py:75-108` (`grants()` fetches `limit*3` then filters by topic in Python; `topic_options` scans up to 120 grants' topic arrays); `routes.py` (fixed `limit=120`/`150`)

Because topic/country live in non-indexable `json` columns ([DATA-2](08-database.md)), the grants
list over-fetches and filters in app code, and there's no cursor/offset pagination — just a hard cap.
Fine at MVP volume; degrades as the corpus grows. Fix via JSONB+GIN ([DATA-2](08-database.md)) and
real pagination. **Effort: small.**

### ⚪ WEBOPS-6 — `/health` leaks the environment string and isn't a real readiness check — `low`
**Location:** `api/routes/health.py:8-15` — returns `app_env` (minor info disclosure) and always
`status: ok` without checking DB/Redis reachability, so it can't gate a load balancer. Make it a
readiness probe (verify DB/Redis) and drop the environment string from the unauthenticated response.
**Effort: trivial.**
