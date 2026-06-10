# Ingestion & web connectors (the scraping layer)

**Assessment: adequate** — the most mature, thoughtfully-engineered part of the MVP, but weak
against real-world hostile conditions and carrying real legal/politeness exposure. *Verification
note: ING-1 and ING-2 were queued for adversarial re-check but the session limit hit first; both
are straightforward factual claims (grep-verifiable) from the original reviewer.*

## Summary

Clean `BaseConnector` contract (discover → fetch_detail → normalize), genuine per-item error
isolation, structured `ConnectorError` reporting, a content-hash-deduplicated raw-snapshot store,
and a non-trivial incremental-vs-backfill refresh policy. Twelve connectors across four discovery
families (EU search API, WordPress REST, RSS, sitemap, HTML, AJAX) each have fixture-based tests.
**But:** no robots.txt handling, the HTTP layer retries 4xx (impolite + futile against blockers),
no pagination anywhere (every source capped at one page), no global concurrency coordinator, and
the HTML scrapers (GURT, GrantForward) rest on brittle selectors that degrade silently. Connector
quality is bimodal: API/feed connectors are solid; HTML scrapers are fragile.

## Strengths

- Well-factored connector abstraction; `BaseConnector.run` and `IngestionService` wrap each item in its own `try/except` (`base.py:38-53`, `service.py:139-173`) — one bad page doesn't kill the run.
- Discovery-level failures isolated too: a thrown `discover()` records a `ConnectorError`, marks the job `partial`, finishes bookkeeping. Counters + bounded error sample persisted to `JobRun`.
- Content-addressed, idempotent raw-snapshot storage dedup'd on `(source_id, source_url, content_hash)` — preserves an audit trail and supports re-extraction without re-scraping.
- Thought-through incremental vs backfill: new items always fetched, known items skipped unless due for refresh, items absent from the listing but still due re-fetched separately. Per-source refresh cadence via `source_metadata`.
- Per-source rate limiting honored (`http.py:74-82`) with sensible seed defaults (gurt/grantforward 8s, eu-funding 2s). Configurable User-Agent.
- URL canonicalization strips tracking params; multilingual (UK+EN) date/deadline extraction.
- **GURT Cloudflare limitation handled with integrity:** docs explicitly state no bypass will be attempted; GURT is excluded from the quality gate rather than faked. This is the right call.
- Every connector has a fixture-based unit test (~893 lines, 14 fixtures) including incremental-skip/refresh-due behavior.

---

## Findings

### 🟠 ING-1 — No robots.txt handling anywhere — `high`
**Location:** `grant_tool/ingestion/http.py` (whole file); no `robotparser` anywhere.

A full-codebase grep for `robots`/`RobotFileParser`/`robotparser` returns zero hits. The client
fetches list pages, sitemaps, RSS, detail HTML, and APIs with no robots consultation and no
crawl-delay awareness — across broad third-party/commercial sites (gurt, grant.market,
fundsforngos, opportunitydesk, grantforward).

**Why it matters:** For a tool whose purpose is scraping many third-party sites, ignoring
robots.txt is both a politeness and a legal/ToS exposure problem — directly relevant for an
ISO-certified consultancy — and makes IP blocking more likely.

**Recommendation:** Per-host robots.txt fetch+cache (`urllib.robotparser`/`reppy`) checked before
each request, honoring `Crawl-delay`; explicit per-source override (recorded with justification)
where you have permission; log/skip disallowed URLs. **Effort: medium.**

### 🟠 ING-2 — HTTP layer retries 4xx (403/401/404) against blocking sites — `high`
**Location:** `grant_tool/ingestion/http.py:59-72`

`_request` catches `httpx.HTTPStatusError` in the same branch as timeouts/transport errors, so a
403 (Cloudflare), 401 (login redirect), or 404 is retried `retries+1` times with backoff. No
distinction between retryable (5xx/timeout/connection) and non-retryable (4xx).

**Why it matters:** Retrying 403/401/429 hammers exactly the sites already rejecting you,
increasing hard-IP-ban risk; retrying 404 wastes rate-limit budget.

**Recommendation:** Retry only on `TimeoutException`/`TransportError`/5xx (and 429 honoring
`Retry-After`); surface other 4xx immediately as `ConnectorError`; add jitter. **Effort: small.**

### 🟡 ING-3 — Untrusted XML (RSS/sitemaps) parsed with stdlib `ElementTree` — `medium`
**Location:** `connectors/common.py:22-34`; used by prostir, wordpress RSS, grant_market, diia sitemap.

`ET.fromstring` on remote attacker-influenceable XML. Stdlib ElementTree doesn't expand external
entities by default but remains susceptible to entity-expansion DoS (billion laughs), and raises
`ParseError` on any malformed body — turning a transient bad response into a whole-source
discovery failure.

**Recommendation:** Use `defusedxml.ElementTree`; wrap parse errors to skip the bad feed + record
a `ConnectorError` rather than aborting discovery. Consider `feedparser` for RSS. **Effort: small.**

### 🟡 ING-4 — No pagination in any connector — silently caps every source at one page — `medium`
**Location:** `eu_funding.py:36` (pageNumber=1), `diia_business.py:83` (skip=0), `grantforward.py:162` (offset=0), grant_market/prostir/wordpress (single fetch). Documented as deferred.

Every connector fetches exactly one page/feed and slices to `limit`. There is no next-page
traversal.

**Why it matters:** In production the tool can only ever see the most-recent page per source per
run; combined with incremental mode skipping known items, older still-open grants are never
discovered. "Backfill" is a misnomer.

**Recommendation:** Add bounded pagination loops (with a max-pages cap) for the API/sitemap/WP-REST
connectors (they expose clean `pageNumber`/`skip`/`offset`/`page` params). Keep HTML scrapers
single-page until selectors are validated. **Effort: medium.**

### 🟡 ING-5 — GURT & GrantForward HTML scrapers rely on brittle selectors and order-dependent heuristics — `medium`
**Location:** `gurt.py:118-128`; `common.py:37-61`; `grantforward.py:184-252`

GURT discovery accepts any anchor whose href merely *contains* `/news/grants/` with link text
≥4 chars — which also catches nav/sidebar/archive links (contrary to the documented intent). Title
falls back to the first `h1/h2/title` (often the site name). GrantForward parses very specific
class names that break on a re-theme, and the connector can't self-detect empty-vs-broken.

**Why it matters:** These connectors degrade **silently** — a layout change yields zero items or
garbage titles, but the run still reports `success, 0 errors`. Breakage is invisible until someone
notices the source stopped producing grants.

**Recommendation:** Tighten GURT link filtering (path must *start with* `/news/grants/`, exclude
listing/archive/anchor links); add a per-connector "expected minimum yield" / selector-presence
assertion that raises a `ConnectorError` on layout drift. **Effort: medium.**

### 🟡 ING-6 — `Source.enabled` / `requires_browser` flags are defined but never honored — `medium`
**Location:** `db/models.py:97-98`; `cli.py:296` (`--all` iterates static `CONNECTOR_CLASSES`); `service.py:50-87`

`run_source` never reads `enabled`/`requires_browser`, and `ingest --all` iterates the static
connector dict rather than enabled sources. So disabling a misbehaving source in the DB has no
effect, and `requires_browser` (the intended mechanism for GURT-style JS/Cloudflare sites) is
still attempted with the plain httpx client.

**Why it matters:** No operational kill-switch for a source that starts failing/blocking/raising
ToS concerns — the only way to stop is a code change. The very situation `requires_browser` was
designed for gets no runtime guard.

**Recommendation:** Filter `run_source`/`--all` on `source.enabled`; short-circuit (or no-op with
a clear skipped reason) when `requires_browser` is true and no browser backend is configured.
**Effort: small.**

### 🟡 ING-7 — Rate limiting is per-process-per-source only; no global politeness coordinator — `medium`
**Location:** `http.py:74-82` (instance-local `_last_request_at`); `celery_app.py` (ingestion not wired); `cli.py:303-304`

`rate_limit_seconds` is enforced inside a single `HttpClient` instance. If ingestion moves to
Celery (the stated stack) or parallel CLI runs, each worker gets a fresh `_last_request_at`, so
concurrent runs against the same host collectively double the request rate. No per-*host* throttle
(several connectors hit overlapping infrastructure / shared CDNs).

**Recommendation:** Move the throttle to per-host granularity backed by a shared store (Redis token
bucket) so it holds across workers; add a per-host concurrency limit before parallelizing. **Effort: medium.**

### 🟡 ING-8 — `ingest --all` is not isolated at the source level — `medium`
**Location:** `cli.py:295-315`; `service.py:240-242`

`_cmd_ingest` loops over sources with no `try/except`; `run_source`'s outer except re-raises
genuinely unexpected exceptions (DB error in bookkeeping, connector `__init__` throw, etc.). With a
single `session.commit()` only after the whole loop, an exception mid-loop aborts all remaining
sources **and** discards earlier successful work in that session.

**Why it matters:** Source-level isolation ("one bad source shouldn't kill a run") is the stated
goal — it holds for in-connector errors but not for the batch driver.

**Recommendation:** Wrap each `run_source` in `try/except`; commit per-source (or use independent
sessions) so a later failure can't discard earlier successes. **Effort: small.**

### 🟡 ING-9 — Legal/ToS exposure: login-gated & aggregator scraping; EU API via hardcoded SEDIA key — `medium`
**Location:** `grantforward.py:34-44,80-83`; `eu_funding.py:36`; `wordpress.py:378-426`; `docs/initial_sources.md:21,52`

GrantForward is accessed via its internal `/search/search` AJAX endpoint with browser-mimicking
headers, while detail pages are explicitly login-gated (the connector even records
`detail_requires_login=True`). EUFundingPortal.eu / fundsforngos / opportunitydesk are aggregators
whose content may be republished under restrictive terms. The EU connector posts a hardcoded
`apiKey='SEDIA'` with `text='***'`. None of this is bypass/malware, and the dev partly mitigates
with `needs_manual_review` flags + docs — but the scraping still happens.

**Why it matters:** For an ISO-certified consultancy, harvesting a commercial site's internal
endpoint and aggregator content carries ToS/copyright risk that should be an explicit, signed-off
decision.

**Recommendation:** Document per-source legal basis / ToS outcome in `source_metadata`; gate
commercial/login-gated sources behind an explicit `enabled` flag + recorded approval; confirm the
SEDIA usage matches the EU portal's published API terms; treat aggregators as lower priority.
**Effort: medium.**

### ⚪ ING-10 — Deterministic field extraction is fragile/order-dependent — `low`
**Location:** `ingestion/utils.py:228-303`; `diia_business.py:417-425` — `extract_deadline` can pick a
publication/event date; `extract_funding_text` returns the first currency number anywhere;
`status_from_deadline` derives open/closed from a possibly-wrong deadline; Diia marks anything
mentioning a year ≥ current as "open." These confident-but-wrong fields feed matching with no
low-confidence signal. Attach a heuristic-source/confidence marker, prefer structured source fields,
route low-confidence to manual review. **Effort: medium.**

### ⚪ ING-11 — WordPress connectors over-fetch full post bodies into `discovery_metadata` — `low`
**Location:** `wordpress.py:126`; `base.py:73-87` — full rendered post HTML stored in
`discovery_metadata['raw_post']` and again in the snapshot, bloating JSON columns; the grant-like
filter is a broad keyword substring match admitting many non-grant posts. Store only
identity+hashes+excerpt; tighten keywords/require category match for broad sources. **Effort: small.**

### ⚪ ING-12 — Connector errors stored as raw `str(exc)`; no transient/permanent classification — `low`
**Location:** `service.py:160-173,202-215`; `types.py:165-170` — no exception-type retention, no
"layout changed / yielded zero" vs "temporarily down" distinction; jobs are `partial` on any error.
Hard to drive alerting. Add an `error_type`/`transient` flag, classify at the catch site, and
signal when a source returns zero where it historically returned many. **Effort: small.**
