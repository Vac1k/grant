# Docs accuracy & product/scope sanity

**Assessment: adequate.** *Written by direct reading of `README.md`, `docs/start.md`,
`docs/implemented_mvp.md`, `docs/technologies.md`, and cross-checking against the code — the
reviewer agent for this dimension did not run before the session token limit. Findings here are my
own; treat severities as my judgement rather than adversarially verified.*

## Summary

The documentation is a genuine strength: `docs/implemented_mvp.md` is a thorough, stage-by-stage
account that is **honest about its own gaps** — it explicitly states the Celery `worker`/`beat`
services are "інфраструктурні заготовки" (infrastructure placeholders), that `document_inventory.csv`
is a manual reference not imported by any CLI command, and that the hash embedding provider is "для
tests/smoke." That candor is rare and worth preserving. The drift that exists is in *framing*, not
*lies*: the tech docs call the system a "REST API" it isn't, and the README's flow description and
the smoke test together imply semantic vector matching is operational when (per
[MATCH-1/2/3](03-matching-embeddings-dedup.md)) the default path runs on fake hash vectors. The
deeper question is product scope: the repo name (`ai_replace_grandwriters`) and README goal frame
this as replacing grant-writers, but what's built is a grant **discovery + shortlisting + manual-
review** tool. That's a perfectly good product — it just isn't grant *writing*, and being clear
about that changes what "done" means.

## Strengths

- `docs/implemented_mvp.md` is comprehensive and maps closely to the code (schema fields, CLI commands, stage flow all match what's implemented).
- The docs are **honest about incompleteness** — placeholders, deferred decisions, and non-imported files are called out rather than hidden. This is the opposite of the usual "docs oversell the code" failure.
- Deferred/blocked sources (GURT Cloudflare, GrantSense) are documented with reasons, and the "do not bypass" stance is stated explicitly — good integrity and good auditability.
- `docs/start.md` / `docs/operations.md` give a real, runnable command sequence (the smoke flow), so a new operator can actually drive the pipeline.
- Per-stage "implemented vs deferred" planning docs give a clear audit trail of decisions — useful for an ISO-style process.

---

## Findings

### 🟡 DOC-1 — Docs imply operational semantic matching; the default path is lexical — `medium`
**Location:** `README.md` ("Flow Системи" step 6, "vector similarity"); `docs/implemented_mvp.md:15,705-711`; smoke flow uses `--provider hash`

The README lists "vector similarity" as part of the live flow and the documented smoke test embeds
with `--provider hash` then matches `--use-vector`. A reader concludes semantic matching is working.
In reality the demonstrated vectors are a token-hash fingerprint and the OpenAI path is never the
default ([MATCH-1](03-matching-embeddings-dedup.md)). The docs *do* note the hash provider is "для
tests/smoke," but they don't warn that the headline smoke test therefore demonstrates non-semantic
matching.

**Why it matters:** This is the gap between perceived and actual product value. Anyone evaluating
"does the AI work?" by running the documented flow gets a misleading positive.

**Recommendation:** State plainly in the README/MVP doc that the default/smoke path is
lexical+history matching, and that real semantic matching requires `--provider openai` (and the
[MATCH-1/2/3](03-matching-embeddings-dedup.md) wiring). Tie the doc fix to the P1.1 decision.
**Effort: trivial.**

### 🟡 DOC-2 — Product framing ("replace grant-writers") overreaches what's built — `medium`
**Location:** repo name `ai_replace_grandwriters`; `README.md` goal ("зменшити ручну роботу з дослідження грантів")

The README's own stated goal is actually the honest one — *reduce manual grant-research work*. But
the project name and the implied ambition point at replacing grant *writers*. What exists is a
research/discovery accelerator: it finds opportunities, normalizes them, shortlists per client, and
queues manual review. It does not draft applications, and the application-history signal is
explicitly "positive relevance only," not outcome-predictive.

**Why it matters:** Scope clarity drives the roadmap. As a *discovery + shortlisting* tool this MVP
is ~70% of a useful product; as a *grant-writer replacement* it's ~15% of a much larger and riskier
one. Deciding which you're building determines whether the next investment is "harden + measure" or
"build a drafting/LLM-generation layer from scratch."

**Recommendation:** Pick the honest framing (discovery + shortlisting + review queue, human in the
loop), state it at the top of the README, and let it set the definition of done. **Effort: trivial.**

### ⚪ DOC-3 — "REST API" framing is inaccurate — `low`
**Location:** `docs/technologies.md:13-17` (also [ARCH-6](06-architecture.md)) — the only API route is
`GET /api/v1/health`; everything else is CLI + read-only dashboard GETs. Reword to "CLI-orchestrated
batch pipeline + read-only FastAPI/Jinja2/HTMX dashboard + health endpoint." **Effort: trivial.**

### ⚪ DOC-4 — Scope sprawl: 11 sources, several fragile, no pagination — a maintenance-vs-value question — `low`
**Location:** `README.md` source list; connectors; ([ING-4](05-ingestion-connectors.md), [ING-5](05-ingestion-connectors.md))

The search stage expanded from 4 planned sources to 11 implemented connectors, several of which are
brittle HTML scrapers capped at one page each and flagged `needs_manual_review`. Breadth was chosen
over depth/reliability.

**Why it matters:** Each fragile source is ongoing maintenance (silent breakage, ToS exposure) for
uncertain marginal value, and none paginates, so "more sources" doesn't even mean "more coverage" —
it means "one more page from more sites." For a solo maintainer this is the scaling trap.

**Recommendation:** Rank sources by reliability × value; invest in deep, paginated, robust coverage
of the few high-value API/feed sources (EU portal, Diia, Prostir) and demote/disable the fragile
aggregator scrapers until they earn their keep. Quality over quantity. **Effort: small** (decision)
**/ medium** (execution).
