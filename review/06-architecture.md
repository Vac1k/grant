# Architecture & design

**Assessment: adequate** — well-organized and appropriate for its actual problem (a
single-operator, batch-oriented grant-research tool). Carry-forward-able with targeted
refactoring; **not** fundamentally flawed. *No findings here were re-verified by a second agent
(none were critical/high); all are medium/low design observations.*

## Summary

The pipeline is cleanly decomposed into independent stage services (ingestion, extraction, dedup,
matching, embeddings, explanations, dashboard), each driven by an argparse CLI and persisting
through a shared repository. The connector framework and the swappable LLM/embedding provider
abstractions are genuinely good decisions that enable offline, deterministic testing. Two stack
elements are vestigial: **Celery/Redis is wired everywhere but runs nothing**, and FastAPI's async
machinery is unused (no `async def`; the real surface is one `/health` route + a read-only
dashboard, not the "REST API" the docs claim). The two biggest design liabilities are a
1,266-line `GrantRepository` god-object and a 1,512-line `FeatureExtractionService` that fuses
generic extraction with source-specific logic. Neither breaks the MVP; both will become
maintenance bottlenecks.

## Strengths

- Clean, consistent stage-service decomposition: each step is its own package with one service class, a CLI command, and a `JobRun` audit trail. Every stage is independently runnable/testable.
- Excellent provider/strategy abstraction for every external-AI dependency (`Protocol` + deterministic offline impl + OpenAI impl). The whole pipeline runs and tests with no API key or network — a strong deliberate choice.
- Sensible connector framework with a shared rate-limiting/retrying `HttpClient`; adding a source is a localized change.
- Raw-snapshot-beside-normalized-record design with content hashing — the right call for provenance/re-extraction.
- Deliberate per-stage resilience (item-level error isolation → `partial` job status).
- Centralized, typed config via `pydantic-settings` + `lru_cache`; correctly configured session factory (`pool_pre_ping`, `expire_on_commit=False`) exposed as both a CLI context manager and a FastAPI dependency.
- Clean constructor-injection of repository/http-client-factory/llm-client, enabling the fixture-based test suite.

---

## Findings

### 🟡 ARCH-1 — Celery + Redis are dead infrastructure (wired everywhere, execute nothing) — `medium`
**Location:** `celery_app.py:1-21`; `docker-compose.yml` (worker/beat); `config.py:14`

`celery_app.py` defines a single `healthcheck` task that nothing references; a repo-wide grep for
`delay(`/`apply_async`/`@task` outside that file is empty. No pipeline stage is a Celery task and
there is no beat schedule, yet compose ships full `worker`/`beat` services and config carries
`redis_url`. The whole pipeline is run by hand via CLI. (The docs honestly admit this.)

**Why it matters:** Carrying a broker + two services + config for a capability that doesn't exist
is misleading (implies async/scheduled processing), adds operational/security surface (exposed
Redis on 6379), and confuses the next engineer about how the system runs.

**Recommendation:** Either delete Celery/Redis until there's a real scheduling need, or commit to
it (wrap ingest/extract/match as real tasks + a beat schedule). Don't leave it half-wired; at
minimum mark the placeholders. **Effort: small.**

### 🟡 ARCH-2 — `GrantRepository` is a 1,266-line, 50-method god object every service couples to — `medium`
**Location:** `grant_tool/db/repositories.py`

Mixes three responsibilities: plain persistence (`upsert_grant`, `save_raw_snapshot`,
`save_match_result`), analytics/reporting (`search_source_report`, `data_audit_report`,
`search_quality_gate_report`), and **business policy** (`_is_quality_approved_grant` at line 824
encodes quality-gate rules inside the repository). Changing any stage tends to mean editing this
one file.

**Recommendation:** Split along the seams — thin per-aggregate CRUD repositories, a separate
read/reporting module, and lift quality-approval policy into the `data_quality` package where the
contract already lives. No behavior change required. **Effort: medium.** (Pairs with [CQ-2](07-code-quality.md).)

### 🟡 ARCH-3 — `FeatureExtractionService` (1,512 lines) fuses generic extraction with source-specific logic — `medium`
**Location:** `grant_tool/extraction/service.py:116-1462`

One class owns title/summary/deadline/funding/taxonomy/geography/confidence/manual-review **and**
hard-coded per-source branches (`enrich_draft` dispatches on `source_slug == 'diia-business'` /
`'eu-funding'` with dedicated helpers). Source-specific knowledge has leaked out of the connectors
into the central extractor.

**Why it matters:** Each new quirky source risks another `if source_slug == ...` branch, growing
an already-1,500-line class and re-coupling the "generic" extractor to specific sites.

**Recommendation:** Extract funding/taxonomy/geography into cohesive modules; move source-specific
normalization back into `connector.normalize()` or per-source strategy objects; keep the service a
generic orchestrator. **Effort: large.**

### ⚪ ARCH-4 — OpenAI calls bypass the project's own HTTP resilience layer — `low`
**Location:** `extraction/service.py:1502-1508`; `embeddings/service.py:79-85`; `explanations/service.py:97-111`

All three LLM/embedding clients do a bare `httpx.post(timeout=60)` + `raise_for_status()` — no
retry/backoff/rate-limit — even though `ingestion/http.py` already has a robust client. Each also
does a function-local `import httpx` and duplicates the OpenAI URL three times. Introduce one
shared LLM HTTP helper with retry/backoff and a single base-URL source of truth. **Effort: small.**
(See [EXT-2](04-llm-extraction.md), [MATCH-6](03-matching-embeddings-dedup.md).)

### ⚪ ARCH-5 — No transactional/run-level coherence across stages — `low`
**Location:** `cli.py:295-448`; `matching/service.py:126`

The "pipeline" is a sequence of independent CLI invocations, each opening its own session and
committing on success. No orchestrating pipeline object, no run-id threading one end-to-end
execution, no rollback if a later stage fails. Partial states (grants ingested but never embedded)
are normal; ordering is enforced only by operator discipline/docs. Acceptable for a manual MVP, but
needs addressing before automation. Consider a lightweight `PipelineRun` id in `job_metadata` and a
single script target over six commands. **Effort: medium.**

### ⚪ ARCH-6 — Docs overstate the system as a "REST API" — `low`
**Location:** `docs/technologies.md:13-17`; `main.py:21-22`; `api/routes/health.py`

The only mounted API route is `GET /api/v1/health`; everything else is CLI + read-only dashboard
GETs. No write/command endpoints, no programmatic trigger API. Reword the docs to describe the real
interface (CLI-orchestrated batch pipeline + read-only dashboard + health endpoint). **Effort: trivial.**
(See [10-docs-and-product.md](10-docs-and-product.md).)

### ⚪ ARCH-7 — Module-level engine/settings instantiation at import time — `low`
**Location:** `db/session.py:9-17`; `celery_app.py:5-11`

`session.py` calls `get_settings()` + `create_engine()` at import time, binding a single global
engine to whatever `DATABASE_URL` exists on first import (and `get_settings` is `lru_cache`d, so
config is frozen process-wide). Awkward for per-test/per-tenant DBs; import-time side effects can
surprise tooling. Consider lazy `get_engine()`/`get_sessionmaker()` factories. **Effort: small.**
