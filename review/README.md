# Project Review — AI Grant Matching Tool

**Date:** 2026-06-09
**Reviewed commit:** `2f32451` (main)
**Scope:** full codebase (~14.7k lines Python, 67 files), docs, infra, tests.
**Method:** multi-agent review across 10 dimensions, with adversarial verification of
the most severe findings. Two reviewer-spawned dimensions (docs/product, web/ops) and
the final synthesis were written by hand after the automated run hit a session token
limit; the two highest-impact findings (no-auth, fake embeddings) were additionally
verified by direct code reading.

## Start here

1. **[00-VERDICT.md](00-VERDICT.md)** — Is this worth continuing or is it trash? Scorecard,
   honest summary, top strengths and risks. **Read this first.**
2. **[01-ACTION-PLAN.md](01-ACTION-PLAN.md)** — Prioritized roadmap (P0 → P3). What to fix
   first, in order, with effort estimates.

## Per-dimension detail

| File | Dimension | Verdict |
|------|-----------|---------|
| [02-security.md](02-security.md) | Security, secrets, dependencies | weak — has the only **critical** |
| [03-matching-embeddings-dedup.md](03-matching-embeddings-dedup.md) | The "AI" core | mixed — dedup strong, semantic layer dormant |
| [04-llm-extraction.md](04-llm-extraction.md) | LLM field extraction | adequate |
| [05-ingestion-connectors.md](05-ingestion-connectors.md) | Scraping layer | adequate — most mature module |
| [06-architecture.md](06-architecture.md) | Architecture & design | adequate |
| [07-code-quality.md](07-code-quality.md) | Code quality & maintainability | adequate |
| [08-database.md](08-database.md) | Data model, migrations, persistence | adequate |
| [09-tests.md](09-tests.md) | Test suite | adequate — but red today |
| [10-docs-and-product.md](10-docs-and-product.md) | Docs accuracy & product viability | adequate |
| [11-web-api-ops.md](11-web-api-ops.md) | Web/API/dashboard & deployment | weak |

## How findings are labelled

- **Severity:** `critical` (security/data/legal blocker) · `high` (real bug or major flaw) ·
  `medium` (quality/maintainability) · `low` (polish).
- **Effort:** `trivial` · `small` · `medium` · `large`.
- IDs (`SEC-1`, `MATCH-2`, …) are stable references used in the action plan.

## One-line bottom line

Not trash. A competently engineered MVP with several genuinely good decisions — but the
headline "semantic AI matching" is not actually running by default, and it cannot leave a
laptop until security (auth, PII, secrets) is fixed. **Carry it forward with focused rework.**
