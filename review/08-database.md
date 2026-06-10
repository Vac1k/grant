# Data model, migrations & persistence

**Assessment: adequate** — genuinely well-designed schema; the serious issues are about *scale*
and the *unused vector path*, not data corruption. *DATA-1 was queued for adversarial re-check but
the session limit hit first; it overlaps [MATCH-2](03-matching-embeddings-dedup.md), which was
independently confirmed by direct code reading.*

## Summary

Nine cleanly normalized tables with UUID PKs, a shared constraint/index naming convention,
deliberate FK `ondelete` policies, and composite indexes on the columns actually filtered. All four
Alembic migrations have working downgrades, form a correct linear chain, and match `models.py`
column-for-column. Repositories consistently use `selectinload`, so there are no accidental N+1s on
the hot paths. The serious problems: **no pgvector ANN index** (similarity brute-forced in Python),
JSON columns use generic `json` not `jsonb` (no indexing/operators), `updated_at` relies on
Python-side `onupdate` while a refresh query depends on it advancing, and **tests run only on
in-memory SQLite** so migrations and real pgvector behavior are never exercised.

## Strengths

- Properly normalized with clear separation: `Source`, `RawGrantSnapshot` (audit), `DiscoveredGrantItem` (discovery), `Grant` (extracted), `ClientProfile`, `ApplicationHistory`, `MatchRun`, `GrantClientMatch`, `Report`. Raw vs extracted separated — right for a scraping pipeline.
- Centralized `NAMING_CONVENTION` in `base.py` → deterministic, migration-friendly constraint names.
- Deliberate, correct FK `ondelete`: CASCADE for owned children, SET NULL for soft references.
- Business uniqueness enforced at the DB level (`uq_grants_source_url`, `uq_grant_client_matches_run_grant_client`, …), agreeing with the upsert helpers.
- Composite indexes on the actually-queried columns (`ix_grants_deadline_at`, `ix_grants_status`, `ix_job_runs_job_type_status`, …).
- All four migrations have real ordered `downgrade()`s — reversible.
- Migrations match the ORM exactly (no detectable drift).
- `selectinload` used consistently on read-heavy paths — no lazy-load N+1.
- Money uses `Numeric(14,2)`, scores `Numeric(6,4)` — correct, no float drift.
- `pool_pre_ping=True` avoids stale-connection errors; `autoflush=False` gives explicit flush control.

---

## Findings

### 🟠 DATA-1 — No pgvector ANN index; similarity computed in Python over the full table — `high`
**Location:** `db/models.py:304,333,376`; `matching/service.py:59,360-395`; `embeddings/service.py:240-249`; all `migrations/versions/*.py`

Three `Vector(1536)` columns exist and the extension is enabled, but no IVFFlat/HNSW index is ever
created and no distance operator (`<->`/`<=>`/`cosine_distance`) is used. Matching loads **all**
grant rows then computes cosine similarity in pure Python for every (grant × client × history)
combination. The whole reason to use pgvector — server-side ANN search — is unused. (Same issue as
[MATCH-2](03-matching-embeddings-dedup.md), from the persistence angle.)

**Why it matters:** O(grants × clients × history) full-table work in the app process, pulling every
1536-float vector into memory on each run. Fine at a few hundred grants; slow and memory-heavy at
tens of thousands; no efficient "top-K nearest grants for this client" query. **The single biggest
scale risk in the persistence layer.**

**Recommendation:** Add a migration creating an HNSW (preferred) index with `vector_cosine_ops` and
push top-K into SQL via `Grant.embedding.cosine_distance(client_vec)` ordered+limited; keep the
Python path only as a hash-provider/test fallback. (IVFFlat needs an explicit `lists` param and a
populated table; HNSW doesn't.) **Effort: medium.**

### 🟡 DATA-2 — JSON columns use generic `sqlalchemy.JSON` (Postgres `json`), not `JSONB` — `medium`
**Location:** `db/models.py` (all JSON columns: countries, regions, applicant_types, topics, keywords, documents, `*_metadata`, parameters, evidence, filter_reasons, manual_checks); migrations declare `sa.JSON()`. Zero `JSONB` usage.

`json` stores a reparsed text blob: no GIN indexing, no containment/key operators (`@>`, `?`),
slower repeated access. The data-audit and dashboard code already filter grants in Python on
topics/countries *precisely because* these columns can't be queried efficiently.

**Recommendation:** Switch to `postgresql.JSONB` (migration with `USING column::jsonb`); add GIN
indexes on frequently filtered taxonomy lists, or normalize into association tables if
filtering/joining becomes central. **Effort: medium.**

### 🟡 DATA-3 — `updated_at` uses Python-side `onupdate` only; the refresh scheduler depends on it — `medium`
**Location:** `db/models.py:66-71` (`onupdate=func.now()`); `repositories.py:456-502` (refresh query reads `Grant.updated_at`); migrations set only `server_default`, no `ON UPDATE` trigger

`onupdate` fires only on ORM-issued UPDATEs. Any out-of-band update (raw SQL, bulk `update()`, a
future maintenance script) leaves `updated_at` stale, and `list_discovered_items_due_for_refresh`
compares it against cutoffs to decide what to re-fetch — so a stale value silently breaks freshness
scheduling. Works today because all writes go through the ORM; a latent bug.

**Recommendation:** Add a Postgres `BEFORE UPDATE` trigger setting `updated_at = now()` (most
robust), or enforce that all writes go through the repository. **Effort: small.**

### 🟡 DATA-4 — Migrations and pgvector are never exercised by tests (SQLite-only) — `medium`
**Location:** every test does `create_engine('sqlite+pysqlite:///:memory:')` + `Base.metadata.create_all()`; no `conftest.py`; Alembic never invoked

Consequences: (1) migrations' upgrade/downgrade never run in CI → drift or a broken downgrade goes
uncaught; (2) `Vector(1536)` degrades to a generic type on SQLite → no test touches real pgvector
SQL, the missing index, or json/jsonb behavior; (3) Postgres-specific semantics (multi-column unique
NULL handling, `server_default now()`, cascades) validated only against SQLite, which differs.

**Why it matters:** The persistence layer's two highest-risk areas — migration correctness and
pgvector — have **zero** coverage. "Tests pass" gives false confidence about production Postgres.

**Recommendation:** Add an integration test running `alembic upgrade head` + a downgrade roundtrip
against real Postgres+pgvector (testcontainers / CI service), a model-vs-migration drift check, and
one real vector query. **Effort: medium.** (See [TEST-3/4](09-tests.md).)

### ⚪ DATA-5 — `search_source_report` issues ~12 count queries per source in a Python loop (N+1) — `low`
**Location:** `repositories.py:504-553`,`555`,`569`,`583` — ~12×N round trips for N sources; `data_audit_report`
loads all grants per source and recomputes completeness in Python. Admin/reporting paths (low
frequency) so minor today, but a classic N+1. Replace with grouped aggregates (`GROUP BY source_id`,
`FILTER (WHERE ...)`) and a windowed/lateral latest-job query. **Effort: medium.**

### ⚪ DATA-6 — Embedding dimension hardcoded to 1536; a different model silently breaks inserts — `low`
**Location:** `models.py:304,333,376` (`Vector(1536)`); `config.py:17-20` (`embedding_model` env-configurable); `embeddings/service.py:18`

Switching `EMBEDDING_MODEL` to `text-embedding-3-large` (3072) produces wrong-length vectors;
pgvector rejects them at INSERT with no early validation. Validate provider output length against
`EMBEDDING_DIMENSION` and fail fast, or derive the column dimension from config and gate model
changes behind a migration. **Effort: small.** (See [MATCH-6](03-matching-embeddings-dedup.md).)

### ⚪ DATA-7 — No connection-pool sizing for web+worker concurrency — `low`
**Location:** `db/session.py:11` — only `pool_pre_ping`; `pool_size`/`max_overflow`/`pool_recycle` at
defaults. Under real FastAPI+Celery concurrency the default 5+10 may exhaust, or many workers each
importing the module may exceed Postgres `max_connections`. Expose these via settings with sane
defaults. **Effort: trivial.**

### ⚪ DATA-8 — Upsert helpers are read-then-write with no concurrent-race handling — `low`
**Location:** `repositories.py:159-200,296-338,377-423,934-981,1115-1163` — SELECT-then-INSERT/UPDATE relying
on DB unique constraints but not catching `IntegrityError`; two concurrent workers on the same
`source_url` can both pass the SELECT and the second `flush` aborts the whole job's transaction.
Single-threaded today, but no idempotent-upsert protection. Use `INSERT ... ON CONFLICT DO UPDATE`
(`pg_insert(...).on_conflict_do_update`) or wrap each item in a savepoint; consider periodic commits
in long runs. **Effort: medium.**
