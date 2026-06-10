# Action Plan — prioritized roadmap

Ordered by what unblocks the most value / risk per unit of effort. Each item links to the
detailed finding. Severities and effort are carried over from the dimension reviews.

---

## P0 — Do before this runs anywhere but your laptop (≈ 1 short week)

These are blockers for *any* shared/staging/production use with real client data.

| # | Action | Finding | Effort |
|---|--------|---------|:------:|
| 0.1 | **Rotate the OpenAI key** currently in your working-tree `.env`, and confirm it was never shared. (It is correctly git-ignored and *not* in history — good — but a live key on disk is a standing exposure.) Going forward inject secrets via a manager, never a file, in shared envs. | [SEC-6](02-security.md) | trivial |
| 0.2 | **Add authentication** to the dashboard and all non-health API routes. At minimum HTTP Basic or reverse-proxy auth; ideally session/OIDC SSO. Gate behind a FastAPI dependency. Do not rely on network obscurity. | [SEC-1](02-security.md) ⚠️ critical | medium |
| 0.3 | **Remove client PII from the repo and history.** Add `data/manual_seed/` (or `*.manual.csv`) to `.gitignore`, move the seed files to an ignored/secured location, and purge them from history (`git filter-repo`/BFG). Confirm the lawful basis for holding the data first. Treat as a minor data incident per Trivium's process. | [SEC-2](02-security.md) | medium |
| 0.4 | **Make the test suite green and keep it green.** Inject a clock into `status_from_deadline` + the matching deadline check; compute fixture deadlines relative to that clock instead of `datetime(2026,12,31)`. Add `pytest`/`pytest-cov` as dev deps and a minimal CI job that runs on push. | [TEST-1](09-tests.md), [TEST-2](09-tests.md), [TEST-5](09-tests.md) | small–medium |

---

## P1 — Make it real and operable (the "is this actually valuable?" work)

This is where you decide whether the product earns its "AI" label and becomes measurable.

| # | Action | Finding | Effort |
|---|--------|---------|:------:|
| 1.1 | **Decide the semantic layer's fate, then finish it or cut it.** Option A (finish): make `openai` the default embedding provider, add an HNSW index migration on `grants.embedding`, query top-K with `<=>` in SQL, and **enable `use_vector` by default** so vector matching runs without a manual flag. Option B (cut): drop pgvector, store embeddings as plain arrays, and update the docs to say "lexical + history matching." Do not stay half-wired. | [MATCH-1](03-matching-embeddings-dedup.md), [MATCH-2](03-matching-embeddings-dedup.md), [MATCH-3](03-matching-embeddings-dedup.md), [DATA-1](08-database.md) | medium |
| 1.2 | **Build a small evaluation set** (30–100 real grants with hand-verified fields; 30–50 client/grant relevance judgments). Report per-field extraction accuracy (deterministic vs +LLM) and matching precision@k. This turns "does it work?" from an assertion into a number and gives you a basis to tune weights. | [EXT-4](04-llm-extraction.md), [MATCH-4](03-matching-embeddings-dedup.md) | medium |
| 1.3 | **Add structured logging** (`logging.getLogger(__name__)`, `logger.exception(...)` at every `except`, handlers configured in `main.py`). Replace silent `except Exception: pass` blocks. Without this, production is a black box. | [CQ-1](07-code-quality.md) | medium |
| 1.4 | **Harden outbound HTTP:** SSRF guard (http/https only, block RFC1918/link-local/loopback, re-check after redirects), response-size cap, and retry **only** on 5xx/timeout (not 403/401/404). Add jitter, honor `Retry-After`. | [SEC-3](02-security.md), [ING-2](05-ingestion-connectors.md) | medium |
| 1.5 | **Add robots.txt handling** + honor per-source `enabled`/`requires_browser` flags (currently defined but ignored). Document the legal basis per source; gate login-gated/commercial sources (GrantForward) behind an explicit recorded approval. | [ING-1](05-ingestion-connectors.md), [ING-6](05-ingestion-connectors.md), [ING-9](05-ingestion-connectors.md) | medium |
| 1.6 | **Make the LLM calls production-grade:** retry/backoff for 429/5xx, `max_tokens` cap, and a content-hash cache so re-runs don't re-pay for unchanged text. Reuse the retry logic you already have in `ingestion/http.py`. | [EXT-2](04-llm-extraction.md), [EXT-5](04-llm-extraction.md), [EXT-6](04-llm-extraction.md), [MATCH-6](03-matching-embeddings-dedup.md) | small–medium |
| 1.7 | **Fix the validation crash bug:** wrap `_validate_llm_result` so a malformed-but-plausible LLM response becomes an `invalid` status + manual review instead of an opaque record failure (`clean_text` raises `TypeError` on a non-string `classification`). | [EXT-1](04-llm-extraction.md) | trivial |

---

## P2 — Scale & maintainability (before the corpus or the team grows)

| # | Action | Finding | Effort |
|---|--------|---------|:------:|
| 2.1 | **Add pagination** to the API/feed/sitemap connectors (EU, Diia, GrantForward, WP-REST, sitemaps). Today every source is silently capped at one page. | [ING-4](05-ingestion-connectors.md) | medium |
| 2.2 | **Add selector-health / minimum-yield assertions** to HTML scrapers (GURT, GrantForward) so layout drift surfaces as an alert instead of a silent zero-result "success." | [ING-5](05-ingestion-connectors.md), [ING-12](05-ingestion-connectors.md) | medium |
| 2.3 | **Split the two god modules.** Carve reporting + quality-policy out of `GrantRepository`; extract funding/taxonomy parsing into modules and push source-specific (Diia/EU) logic back into the connectors. | [ARCH-2](06-architecture.md), [ARCH-3](06-architecture.md), [CQ-2](07-code-quality.md) | large |
| 2.4 | **Decide Celery's fate.** Either wire `ingest`/`extract`/`match` as real Celery tasks with a `beat` schedule (so the pipeline isn't six manual CLI commands), or delete Celery/Redis until you need it. It currently runs nothing. | [ARCH-1](06-architecture.md), [ARCH-5](06-architecture.md) | small–medium |
| 2.5 | **Persistence robustness:** switch JSON→JSONB (+GIN on `topics`/`countries`), add a DB-level `updated_at` trigger, size the connection pool, and use `INSERT ... ON CONFLICT` (or savepoints) for upserts. | [DATA-2](08-database.md), [DATA-3](08-database.md), [DATA-7](08-database.md), [DATA-8](08-database.md) | medium |
| 2.6 | **Add integration tests on real Postgres+pgvector** (testcontainers): run `alembic upgrade/downgrade`, a model-vs-migration drift check, and one real vector query. Also test the OpenAI clients with a mocked transport. | [DATA-4](08-database.md), [EXT-3](04-llm-extraction.md), [TEST-3](09-tests.md), [TEST-4](09-tests.md) | medium |
| 2.7 | **Demote brittle "non-grant"/"nonprofit-only" hard filters to manual-review flags** with word-boundary matching, and make filtered grants inspectable. False negatives are currently invisible. | [MATCH-5](03-matching-embeddings-dedup.md) | small |

---

## P3 — Polish & correctness nits

| # | Action | Finding | Effort |
|---|--------|---------|:------:|
| 3.1 | **Reframe the docs** to match reality: a CLI-orchestrated batch pipeline + read-only dashboard, doing *discovery & shortlisting* (not "REST API", not "replace grant-writers"). | [ARCH-6](06-architecture.md), [10-docs-and-product.md](10-docs-and-product.md) | trivial |
| 3.2 | **Container & deploy hardening:** non-root user, pinned base image by digest, a prod compose without `--reload`/bind-mounts/`grant:grant` creds, baseline security headers. | [SEC-4](02-security.md), [SEC-5](02-security.md), [SEC-8](02-security.md) | small |
| 3.3 | **Use `defusedxml`** for remote RSS/sitemap parsing (billion-laughs/XXE hardening + graceful degradation on bad feeds). | [ING-3](05-ingestion-connectors.md) | small |
| 3.4 | **De-duplicate copy-pasted helpers** (`_set_field_evidence`, `_merge_list`, `_decimal`, the currency regex) into shared modules; add evidence-grounding verification; fix `RuleBasedExplanationClient` echoing `final_score` into `llm_score`. | [CQ-3](07-code-quality.md), [EXT-9](04-llm-extraction.md), [MATCH-8](03-matching-embeddings-dedup.md) | small–medium |
| 3.5 | **Add docstrings & promote magic constants** on the central modules; document the `_has_only_soft_warnings` pre-filter assumption (refactor trap). | [CQ-7](07-code-quality.md) | small |
| 3.6 | Validate embedding dimension against the column; replace the maintainer's student email; narrow bare `except Exception` on Decimal coercions. | [DATA-6](08-database.md), [SEC-7](02-security.md), [CQ-8](07-code-quality.md) | trivial |

---

## Sequencing note

P0 is a hard gate — don't deploy past localhost without it. P1.1 and P1.2 are the items that
actually answer "is this product worth it"; do them early even though they're not the cheapest,
because everything else is wasted effort if the matches turn out to be noise. P2/P3 are
ordinary maturation work you can spread out.
