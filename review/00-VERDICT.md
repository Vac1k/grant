# Verdict: Proceed — with focused rework

> **Is this trash? No.** This is a competently built MVP — well above what "solo dev + AI
> agent" usually produces. **Is it production-ready? Also no.** It cannot leave a single
> laptop until a handful of security and correctness blockers are fixed, and its headline
> value proposition ("semantic AI matching") is currently mostly scaffolding.
>
> **Recommendation: carry it forward.** The bones are good. But spend the next effort on
> three things, in order: (1) make it safe to deploy, (2) make the "AI" actually do
> something the keyword scorer doesn't, (3) prove match quality with a real evaluation set.
> If you do all three and the matches still aren't useful, *then* reconsider. Right now you
> can't tell, because nothing measures it.

---

## The honest summary

You have built a clean, batch-oriented grant-research pipeline: scrape ~11 sources →
store raw snapshots → extract structured fields (deterministic, with an LLM fallback) →
deduplicate → match against client profiles → explain → show in a read-only dashboard.
The decomposition is legible, every stage is independently runnable and testable, and the
documentation is unusually honest about what is and isn't implemented.

But two things are true at once:

1. **The engineering is solid where it's deterministic.** The connector framework,
   raw-snapshot provenance, the deduplication module, the quality contract, item-level
   error isolation, and the offline-deterministic test design are all real, thoughtful work.

2. **The "AI" half is largely dormant.** This is the single most important finding:
   - The default (and only tested) embedding provider is a **SHA-256 hash of tokens** — a
     lexical fingerprint, *not* semantic embeddings ([MATCH-1](03-matching-embeddings-dedup.md)).
     The documented smoke test runs on these fake vectors.
   - **pgvector is declared but never actually used** — no ANN index, no `<=>` operator;
     similarity is brute-forced in Python over the whole table ([MATCH-2](03-matching-embeddings-dedup.md), [DATA-1](08-database.md)).
   - Vector matching is **opt-in via a CLI flag only** and unreachable from the dashboard or
     any scheduled path ([MATCH-3](03-matching-embeddings-dedup.md)).

   So in any default/automated run, the product is a **keyword-and-history shortlister
   dressed as semantic AI matching**. That may still be useful — but it is not what the docs
   imply, and nobody has measured whether the matches are good.

And one blocker dominates the deployment decision:

3. **The dashboard exposes confidential client data with zero authentication**
   ([SEC-1](02-security.md), verified **critical**). The moment this runs anywhere but
   `localhost`, it is a confidentiality breach — directly relevant to Trivium's ISO 27001
   obligations. Client PII is also committed into the git repo ([SEC-2](02-security.md)).

None of these are fatal. All are fixable. That's why the verdict is *proceed*, not *abandon*.

---

## Scorecard

| Dimension | Score /10 | One-line |
|-----------|:--------:|----------|
| Architecture & design | **7** | Clean stage decomposition; good provider abstractions; Celery/async are vestigial. |
| Code quality | **6** | Modern typing, no smoke tests; but no logging anywhere, two 1.2k–1.5k-line god modules. |
| **Security** | **3** | No auth on a PII dashboard (critical), committed PII, SSRF, root container. |
| Ingestion & connectors | **6** | Most mature module; but no robots.txt, retries 4xx, no pagination, brittle scrapers. |
| LLM extraction | **6** | Smart gated-fallback design; un-hardened transport, unmeasured quality. |
| Matching / embeddings / dedup | **5** | Dedup is excellent; the semantic layer is scaffolding, weights uncalibrated. |
| Database | **6** | Well-normalized, reversible migrations; pgvector unused, JSON not JSONB, SQLite-only tests. |
| Tests | **5** | Real assertions on core logic; **red today**, time-bomb fixtures, external paths untested. |
| Docs & product | **6** | Docs honest and thorough; product framing ("replace grant-writers") overreaches. |
| Web / API / ops | **4** | No auth, dev-only compose, no observability, pipeline run by hand. |

**Weighted overall: ~5.5/10 as it stands today; ~7.5/10 of *potential* once the P0/P1 work lands.**
The gap between those two numbers is the whole point: this is a good foundation with a
thin, unfinished, and oversold "intelligence" layer sitting on top of it.

---

## Top 6 strengths (keep these)

1. **Stage-service decomposition + provider abstraction.** Each stage is its own package with
   a CLI command and a `JobRun` audit trail, and every external-AI dependency (LLM, embeddings,
   explanations) is a swappable `Protocol` with a deterministic offline implementation. This is
   what makes the whole pipeline runnable and testable with no API key or network — a deliberate,
   mature choice.
2. **Raw-snapshot-beside-normalized-record provenance** with content hashing. The right design
   for a scraping/LLM pipeline: you can re-extract and audit without re-scraping.
3. **The deduplication module.** Weighted multi-signal pair scoring, union-find grouping with
   path compression, and a thoughtful multi-key primary-record selection. Genuinely good.
4. **Item-level error isolation.** One bad detail page or normalization failure is captured as a
   `ConnectorError` and the run continues and finishes `partial`. Mature error handling.
5. **The grant quality contract + normalization** layer, with a real `subTest` matrix of tests
   pinning the noise-classification behavior.
6. **Honest documentation.** The docs explicitly say Celery `worker`/`beat` are placeholders,
   that the hash provider is for tests/smoke, and that `document_inventory.csv` isn't imported.
   That candor is rare and valuable — it means the docs don't lie even where the product is incomplete.

## Top 7 risks (fix these)

1. **No authentication on a dashboard serving client PII** ([SEC-1], critical). ISO 27001 breach the moment it's shared.
2. **The semantic-AI value proposition isn't actually delivering** ([MATCH-1/2/3]). Fake embeddings by default, pgvector unused, vector path opt-in only.
3. **Client PII committed to git** ([SEC-2]) — persists in history, can't be removed by deletion alone.
4. **Zero observability** ([CQ-1]) — `logging` is used in 0 of 67 files; production incidents would require database archaeology.
5. **Test suite is red today and time-bombed** ([TEST-1/2]) — one test already fails on 2026-06-09; ~20 more expire on 2026-12-31. No CI enforces anything.
6. **Scraping legal/politeness exposure** ([ING-1/2/9]) — no robots.txt, retries 403/401, scrapes login-gated/commercial endpoints. Sharp for an ISO-certified consultancy.
7. **Match quality is unmeasured** ([EXT-4], [MATCH-4]) — no golden set, uncalibrated weights. You literally cannot answer "do the matches help?" with data.

---

## What "proceed" is conditional on

Carry it forward **if** you are willing to:

- **Treat it as a grant *discovery + shortlisting + review-queue* tool**, not a grant-*writer*
  replacement. That framing is honest and the tool genuinely serves it.
- **Spend the P0 week** ([01-ACTION-PLAN.md](01-ACTION-PLAN.md)) on security before any
  non-laptop use. This is non-negotiable for client data under ISO 27001.
- **Make a deliberate call on the semantic layer**: either finish it (real embeddings by
  default + pgvector index + wire it into the default path) or drop pgvector and be honest
  that it's lexical matching. Half-wired is the worst state.
- **Build a small evaluation set** so the "is it useful?" question becomes measurable rather
  than aspirational.

If the answer to those is "no" — if this is meant to be a fully-automated grant-writer with
no human in the loop and no appetite for the hardening above — then the scope is mismatched to
the implementation and you'd be polishing the wrong thing. But as an internal,
human-in-the-loop research accelerator, it is well worth continuing.
