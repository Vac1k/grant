# Security, secrets & dependencies

**Assessment: weak** (holds the only `critical`). *Verification note: SEC-1 and SEC-3 were
independently re-verified by a second agent — both confirmed. SEC-2 was not re-verified by
the second pass (session limit) but the underlying facts are confirmed by `git ls-files`.*

## Summary

Secret *hygiene* is actually sound: `.env` is git-ignored, **never committed** (`git log
--all -- .env` is empty and a history scan for `sk-` finds nothing), `.dockerignore` excludes
it, and only `.env.example` with blank placeholders is tracked. The DB layer is **safe from
SQL injection** — every query uses SQLAlchemy 2 `select()`/ORM with bound parameters; there
is no raw SQL, `text()`, or f-string query building anywhere. Jinja2 autoescaping is on (no
`| safe`/`Markup()`), so stored XSS from scraped content is mitigated, and the LLM extraction
output is validated/clamped before persistence.

The real problems are exposure, not injection: **the entire dashboard runs with no
authentication over confidential client data**, and **real client PII is committed to git**.
Secondary: an SSRF-able, unbounded HTTP fetcher and a live key sitting in the working-tree `.env`.

## Strengths

- Secret hygiene correct: `.env` git-ignored + verified absent from history; only `.env.example` tracked; excluded from Docker images.
- No SQL injection surface anywhere (ORM + bound params throughout, including the pgvector path).
- XSS mitigated by default Jinja2 autoescaping; external links use `rel="noreferrer"`.
- LLM prompt-injection blast radius deliberately contained: untrusted scraped text goes in the `user` role, `temperature=0`, `response_format=json_object`, output strictly validated/clamped and cannot overwrite good deterministic fields.
- Ingestion source URLs are statically configured in `sources.py` (removes the most direct SSRF vector for the *seed* URLs).
- Dependencies sanely pinned (`fastapi<1.0`, `sqlalchemy<3.0`, …) with a committed `poetry.lock`; no abandoned/malicious packages.

---

## Findings

### 🔴 SEC-1 — Dashboard and API exposed with no authentication whatsoever — `critical`
**Location:** `grant_tool/main.py:11-24`, `grant_tool/dashboard/routes.py:34-133`, `grant_tool/api/routes/health.py`
**Verified:** ✅ confirmed `critical` by adversarial re-check.

`create_app()` mounts the dashboard and API with no auth middleware, no dependency-based auth,
and no network restriction. A grep for `auth|login|token|HTTPBasic|Bearer|Security|middleware`
across `main.py`, `api/`, `dashboard/` returns nothing. Every route (`/`, `/grants`,
`/clients`, `/matches`, `/report`) is an open `GET`. The dashboard surfaces confidential
client profiles (`name`, `sector`, `product_description`, `risks`), application history
(`client_name`, `project_summary`, `result`, `notes`), and match results. `docker-compose.yml`
binds the app to `0.0.0.0:8000`.

**Why it matters:** This is the core product UI over confidential client data. Under Trivium's
ISO 27001 / data-protection obligations, an unauthenticated internal tool serving client PII is
a direct confidentiality breach the moment it leaves a single developer's loopback. There is no
audit trail of who viewed what. (Minor correction from the verifier: the only `/api/v1`
endpoint that exists is `/health`, which leaks the environment string but not client data — all
confidential exposure is via the dashboard routes. Does not change the rating.)

**Recommendation:** Add authentication before any shared/staging/production deployment — at
minimum HTTP Basic or reverse-proxy auth, ideally session/OIDC SSO. Gate all dashboard and
non-health routes behind a FastAPI dependency. **Effort: medium.**

### 🟠 SEC-2 — Real client business data (PII) committed to git — `high`
**Location:** `data/manual_seed/client_profiles.manual.csv`, `application_history.manual.csv`, `document_inventory.manual.csv`

These CSVs are tracked (`git ls-files` confirms) and contain populated rows, not just headers:
5 client profiles, 12 application-history records, and 18 document-inventory rows whose schema
includes an explicit `contains_sensitive_data` column. Note the asymmetry: `initial_grants/`
*is* in `.gitignore` but `data/manual_seed/` is **not**, so this client data is permanently in
history.

**Why it matters:** Committing identifiable client business information to source control
violates confidential-by-default and data-minimization rules and ISO 27001 controls. Anyone
with repo access (now or future — clones, forks, CI mirrors) gets it, and deletion alone does
not remove it from history.

**Recommendation:** Move seed files out of the repo (ignored local path or secured store), add
`data/manual_seed/` to `.gitignore`, and purge from history (`git filter-repo`/BFG) after
confirming the lawful basis. Treat as a minor data incident per Trivium's process. **Effort: medium.**

### 🟠 SEC-3 — HTTP fetcher follows redirects with no SSRF protection and no size limit — `high`
**Location:** `grant_tool/ingestion/http.py:33-37,59-72,84-99`; `base.py:38-53`; `connectors/common.py:37-61`
**Verified:** ✅ confirmed `high` by adversarial re-check.

`HttpClient` is built with `follow_redirects=True` and no allowed-host/scheme checks; `_to_response`
reads `response.text` with no `max_bytes`/streaming cap. Detail URLs are **not** all static —
connectors discover links by scraping listing-page HTML (e.g. GURT accepts any `<a href>`
containing `/news/grants/`) and then `fetch_detail` GETs the scraped URL. `canonicalize_url`
does not restrict scheme or host. So a compromised/malicious source page can redirect or point
the fetcher at `169.254.169.254` (cloud metadata), `localhost` services, or RFC1918 hosts — or
at a huge/slow response. The verifier confirmed ingestion runs as containerized server-side
workers in compose, making this the classic SSRF-to-metadata scenario once deployed.

**Why it matters:** Classic SSRF path to cloud metadata / internal services on a cloud host,
plus memory-exhaustion DoS from a single malicious page. Not exploitable on a laptop today;
becomes serious server-side.

**Recommendation:** Enforce http/https-only; resolve and block private/link-local/loopback IPs
(re-check after each redirect, or cap redirects); stream responses with a `max_bytes` guard +
`Content-Length` pre-check; consider pinning each connector to its expected host(s). **Effort: medium.**

### 🟡 SEC-4 — Production-shaped compose runs `uvicorn --reload` with hardcoded DB creds — `medium`
**Location:** `docker-compose.yml:24,35-39,94-99`

The `app` service runs `uvicorn ... --reload` and bind-mounts source as a live volume; the `db`
service hardcodes `grant/grant/grant` and the default `DATABASE_URL` embeds those creds. There
is no separate prod compose/profile, so this single file is what a deployer reaches for.

**Why it matters:** `--reload` is dev-only (extra attack surface, file-watching, worse perf), and
source bind-mounts + weak shared creds are unsafe outside local dev.

**Recommendation:** Split a production compose/profile without `--reload`/bind-mounts; require
strong DB creds via env/secrets; document that the current file is local-only. **Effort: small.**

### 🟡 SEC-5 — Container image runs as root — `medium`
**Location:** `Dockerfile:1-18`

Built from `python:3.12-slim`, never creates/switches to a non-root user; `CMD` runs uvicorn as root.

**Why it matters:** Violates least-privilege; any RCE/container escape (more plausible given
SEC-3) runs with maximal privileges. ISO 27001 hardening expects non-root containers.

**Recommendation:** Add a non-root user (`adduser`, `chown /app`, `USER appuser`) before `CMD`;
pin the base image by digest. **Effort: small.**

### 🟡 SEC-6 — Live-looking OpenAI key in the working-tree `.env` — `medium`
**Location:** `.env` (`OPENAI_API_KEY`)

The local `.env` contains a populated `sk-`-prefixed key (~164 chars; value intentionally not
reproduced anywhere in this review). It is correctly git-ignored and absent from history — so
**not** a repo leak — but a live credential on disk would be captured by any future broad
`git add -f`, backup, or archive of the folder.

**Why it matters:** A live key on disk is a standing exposure of a billable credential.

**Recommendation:** Rotate it if there is any chance it was shared; keep relying on `.gitignore`
(already correct); never `git add -f`; inject via a secrets manager in shared envs. **Effort: trivial.**

### ⚪ SEC-7 — Maintainer personal/student email in `pyproject.toml` — `low`
**Location:** `pyproject.toml:6` — a real individual's `@stud.th-rosenheim.de` address. Data-minimization nit + odd provenance for a Trivium tool. Use a role/company contact. **Effort: trivial.**

### ⚪ SEC-8 — Static mount + missing security headers — `low`
**Location:** `grant_tool/main.py:13,20` — `StaticFiles` mounted unconditionally (startup fails if dir missing); no CSP/`X-Content-Type-Options`/`X-Frame-Options`. No traversal risk (Starlette is safe). Add baseline security headers via middleware once auth lands. **Effort: small.**
