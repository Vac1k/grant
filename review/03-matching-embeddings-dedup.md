# Matching, embeddings & deduplication — the "AI" core

**Assessment: mixed** — the deterministic core (filters, keyword scoring, dedup) is genuinely
well-engineered; the semantic/"AI" half is largely scaffolding. *Verification note: MATCH-1/2/3
were queued for adversarial re-check but the second pass hit the session limit. MATCH-1
(fake embeddings) and MATCH-2 (pgvector unused) were instead **independently confirmed by direct
code reading** during this review — both are accurate.*

## Summary

The deterministic scoring (hard filters → keyword/topic/tech overlap → history boost, all in
`Decimal` with full evidence trails) is clear, auditable, and well-tested. **Deduplication is
the single best module in the codebase.** But the headline "semantic AI matching" does not run
in practice:

- The default embedding provider is a **hash**, not real semantics.
- **pgvector is declared but never used** — no index, no `<=>`, brute-force Python similarity.
- Vector matching is **opt-in via `--use-vector`** and unreachable from the dashboard/Celery.

So the realistic default behavior of the deployed tool is **keyword-and-history shortlisting**.
That can be useful — but it's not what's advertised, and nobody has measured whether it's good.

## Strengths

- Deterministic keyword/history scoring with explicit, auditable weights (topics 0.45, tech 0.30, applicant 0.15, sector 0.10) and full evidence dicts (`matching/service.py:323-358`).
- **Deduplication** (`deduplication/service.py`): weighted multi-signal pair scoring (canonical URL 0.55, title-similarity tiers, deadline/funder/amount), union-find with path compression, and a thoughtful multi-key primary selection (quality tier > source family > status > completeness > confidence > length > recency).
- Title normalization strips bilingual stopwords/parentheticals; similarity combines `SequenceMatcher` ratio + token Jaccard — sound for noisy aggregator titles.
- Dedup integrates cleanly: duplicates become a hard filter reason; potential duplicates raise manual-review checks; nothing is deleted, only soft-flagged.
- Cosine similarity implemented correctly with length/zero-norm guards; the `max(stage6, vector_blended)` blend means vector can only raise the score, never corrupt the deterministic floor.
- The LLM explanation prompt explicitly forbids overriding deterministic scores and treating `lost`/`rejected` history as negative evidence — a thoughtful guardrail.
- All 12 matching/dedup/embedding tests pass (today) and cover ranking, quality-gate filtering, primary selection, vector fallback, rule-based explanation.

---

## Findings

### 🟠 MATCH-1 — Default and only-tested embedding provider is a fake hash, not semantics — `high`
**Location:** `grant_tool/embeddings/service.py:46-68,257-259`; `cli.py:558`; `tests/test_stage7_embeddings.py`
**Independently confirmed by direct code reading.**

`HashEmbeddingProvider` builds vectors by SHA-256-hashing each token into a bucket and summing
signs (`service.py:57-68`). This is a lexical bag-of-tokens fingerprint, not a semantic
embedding: two grants about the same topic worded differently get near-zero cosine; it cannot
capture synonymy, paraphrase, or cross-language meaning. The `EmbeddingService` default is
`provider_name="hash"` (`service.py:97-100`), the CLI defaults to `--provider hash`
(`cli.py:558`), the documented smoke flow uses `hash`, and **every** embedding/vector test uses
it. `OpenAIEmbeddingProvider` has zero test coverage.

**Why it matters:** The product is framed as semantic AI matching. As shipped/documented, the
semantic layer adds essentially nothing beyond the lexical overlap the keyword scorer already
computes — and the only path a reviewer or new operator will run (the hash smoke test) gives a
**misleading impression that semantic matching works**.

**Recommendation:** Make `openai` the production default (or fail loudly if no real provider is
configured for a non-test run); add at least one integration test exercising
`OpenAIEmbeddingProvider` against a recorded/mocked response; label the hash provider clearly as
test-only. **Effort: medium.**

### 🟠 MATCH-2 — pgvector declared but never used: no index, brute-force Python similarity — `high`
**Location:** `matching/service.py:59,360-395`; `repositories.py:1044-1048`; `migrations/.../0003_add_embedding_columns.py:23-29`
**Independently confirmed by direct code reading.** (Same issue from the DB angle: [DATA-1](08-database.md).)

`Vector(1536)` columns are created and the extension enabled, but **no HNSW/IVFFlat index is
ever created** and **no pgvector distance operator** (`<->`, `<=>`, `cosine_distance`) is used
anywhere. Matching loads *all* grants via `list_grants_for_matching` (no vector predicate), then
computes cosine similarity in pure Python for every (client × grant) and (grant × history) pair.
The entire reason to use pgvector — server-side indexed ANN search — is unrealized.

**Why it matters:** At a few hundred grants it's merely slow; at the scale implied by "many
sources" it becomes a memory/latency problem, and the pgvector dependency buys nothing today.

**Recommendation:** Either (a) push retrieval into Postgres — add an HNSW index migration and
query top-K with `embedding <=> :vec` before deterministic re-ranking; or (b) if brute-force is
acceptable for the expected corpus, drop pgvector, store plain arrays, and document the scale
ceiling. Don't keep a half-wired vector store. **Effort: medium.**

### 🟠 MATCH-3 — Vector similarity is opt-in (CLI only) and unreachable from dashboard/Celery — `high`
**Location:** `matching/service.py:55`; `cli.py:395,548`; `celery_app.py:1-22`; `dashboard/routes.py:101-115`

`use_vector` defaults to `False` and is set only by the `--use-vector` CLI flag. The dashboard
is read-only (serves saved matches; never triggers a run) and `celery_app.py` has only a
healthcheck task. So in any non-manual invocation the vector score is `None` and matching
reduces to `keyword*0.75 + history*0.25`.

**Why it matters:** The "matching via pgvector similarity" value proposition is effectively
dormant in normal operation. Combined with MATCH-1/2, the realistic default is keyword-and-history
shortlisting — be honest about that when deciding whether to invest further.

**Recommendation:** Decide whether vector blending is part of the product; if so, enable it by
default (the missing-embedding fallback already exists) and wire match runs into the
scheduled/dashboard path. **Effort: medium.**

### 🟡 MATCH-4 — Vector blend weights uncalibrated; `max()` blend can mask poor semantic fit — `medium`
**Location:** `matching/service.py:154-161`

`score = max(stage6_score, vector_blended_score)` means the vector contribution can only ever
*raise* the score — a grant with strong keyword overlap but weak semantic relatedness keeps its
high keyword score. The blend weights (0.45/0.35/0.20) are hand-picked with no documented
calibration, and the `+0.05 * extraction_confidence` bump is applied on top, so confidence can
push results over thresholds in ways hard to reason about. No held-out evaluation exists.

**Why it matters:** Uncalibrated weights are the difference between a useful shortlist and
plausible-looking noise — and `max()` structurally prevents semantic signal from down-ranking
lexical false positives.

**Recommendation:** Build a small labelled relevance set (30–50 judgments), tune against
precision@k / nDCG, consider a true weighted blend over `max()`, and record the weights +
evaluation in docs. **Effort: medium.** (Pairs with [EXT-4](04-llm-extraction.md).)

### 🟡 MATCH-5 — Heuristic "non-grant"/"nonprofit-only" filters risk silently dropping real grants — `medium`
**Location:** `matching/service.py:242-247,272-288,467-477`

`_looks_like_non_grant_opportunity` hard-fails any grant whose title contains substrings like
` training `, ` workshop `, `стипенді`, `тренінг`; many real funding calls include training
components. `nonprofit_only_grant` hard-excludes grants mentioning `civil society` / `громадські
організації` unless the client is typed `ngo` — but client type is *inferred from free text*, so
a misclassified client loses eligible grants. These are silent hard filters (counted only in
`filtered_count`), so false negatives are invisible.

**Why it matters:** For a discovery tool, false negatives (missing a real grant) are the most
damaging and least observable failure. Substring heuristics over bilingual free text will quietly
suppress valid opportunities.

**Recommendation:** Demote these to manual-review/down-rank signals, require word-boundary
matching, and make filtered grants inspectable. **Effort: small.**

### 🟡 MATCH-6 — OpenAI providers hardcode endpoints/params; no retry, no dimension safety — `medium`
**Location:** `embeddings/service.py:71-88`; `explanations/service.py:80-113`; `config.py:17-20`

Direct `httpx` calls, no retry/backoff, no 429/5xx handling. The column is fixed at
`Vector(1536)` but `EMBEDDING_MODEL` is operator-configurable — switching to
`text-embedding-3-large` (3072 dims) would silently fail inserts with no validation.

**Recommendation:** Add retry/backoff + 429/5xx handling, validate returned length against
`EMBEDDING_DIMENSION` before persisting, pin the model or gate changes behind a migration.
**Effort: small.** (See also [EXT-2](04-llm-extraction.md), [DATA-6](08-database.md).)

### ⚪ MATCH-7 — Deduplication is O(n²) all-pairs with no blocking — `low`
**Location:** `deduplication/service.py:95-117` — nested loop over all grant pairs, each invoking
`SequenceMatcher` + quality evaluation. Fine now, quadratic as the table grows. Add a cheap
blocking key (normalized-title prefix / funder / deadline date) before pairwise scoring. **Effort: small.**

### ⚪ MATCH-8 — Rule-based explanation sets `llm_score = final_score` — `low`
**Location:** `explanations/service.py:71-77`; `matching/service.py:105` — the offline provider
copies the deterministic score into the field meant for LLM-explanation confidence, contradicting
the documented contract and making `llm_score` a meaningless duplicate wherever displayed. Return
a neutral/`None` value instead. **Effort: trivial.**
