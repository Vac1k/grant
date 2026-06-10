# Test suite — coverage & quality

**Assessment: adequate** — genuinely strong assertions on core logic for a solo MVP, **but the
suite is red today**, time-bombed, and has zero coverage of the external-API code. *TEST-1/TEST-2
were queued for adversarial re-check but the session limit hit first; TEST-1's failure was
empirically demonstrated by the original reviewer running `python -m unittest`.*

## Summary

95 tests across 13 files (~3,600 lines) that assert real behavior, not smoke. The hardest business
logic is covered well — matching scoring with score-breakdown/evidence assertions, the
noise-classification quality contract via `subTest` matrices, soft-dedup primary/duplicate
selection wired through to the matching gate, and a real FastAPI `TestClient` rendering Jinja2
templates. HTTP is properly mocked (a `FakeHttpClient` that raises on any unexpected URL), so the
suite never touches the network. **However:** one deadline test already fails as of 2026-06-09
because `status_from_deadline` reads `datetime.now(UTC)` with no injectable clock; ~20 more hardcode
`datetime(2026,12,31)` as "the future" and will flip to failing once that date passes. The three
OpenAI network clients and the entire CLI command layer are untested. No `pytest`/coverage dep is
declared and there is no CI, so nothing enforces the green bar.

## Strengths

- Tests assert real, specific behavior: exact score breakdowns, `filter_reasons`, evidence structure, `manual_checks`, rank (`test_stage6_matching.py:128-140`); dedup tests verify primary-vs-duplicate AND that the aggregator is filtered out of matching (`test_data_deduplication.py:152-163`).
- Network correctly isolated: `FakeHttpClient` raises `AssertionError` on any URL not pre-seeded; every connector test backed by a captured fixture.
- The most business-critical noise filter (quality contract) is the best-tested area — a `subTest` matrix over digest/webinar/event/news/article noise asserting tier/flags/reasons/eligibility.
- Genuine integration coverage of the dashboard: real `TestClient` with DB override renders all pages and asserts seeded data appears in the HTML.
- Hard parsing edge cases deliberately pinned: EU multi-cutoff deadlines, budget-IDs/KVED-codes/years wrongly read as funding, CAD-vs-USD collision, generic-title recovery.
- Incremental-ingestion logic (skip-known, refresh-when-due, refresh-absent) tested across all connectors — the trickiest scheduling branch.

---

## Findings

### 🟠 TEST-1 — Suite is not green: no injectable clock; one test already fails today — `high`
**Location:** `ingestion/utils.py:296-302`; `tests/test_stage5_extraction.py:537-549`

`status_from_deadline()` calls `datetime.now(UTC)` directly with no clock injection. The test
`test_deadline_parser_ignores_publication_date_and_reads_ukrainian_month` hardcodes a 2026-06-04
deadline and asserts `status == 'open'`; run today (2026-06-09) it **FAILS** (`'closed' != 'open'`,
1 of 95). `test_deadline_parser_reads_two_digit_year_and_not_later_phrase` (2026-06-10) fails
tomorrow. No `freezegun` or clock injection anywhere.

**Why it matters:** A suite that is red on the calendar it's run is worse than no suite — it trains
the team to ignore failures, and the green bar the dev relied on while building was an artifact of
the date. It also hides whether `status_from_deadline` is actually correct.

**Recommendation:** Add `now: datetime | None = None` to `status_from_deadline` (and the matching
deadline check at `matching/service.py:249`), defaulting to `datetime.now(UTC)`; pass a fixed
reference in tests. Or add `freezegun` and `@freeze_time` the date-relative tests. **Effort: small.** *(P0.)*

### 🟠 TEST-2 — ~20 tests hardcode `datetime(2026,12,31)` as "the future" — time bomb — `high`
**Location:** `test_stage6_matching.py` (8), `test_data_deduplication.py` (5), `test_stage7_embeddings.py` (3), + contract/dashboard/explanation tests

These seed grants with `deadline_at=datetime(2026,12,31)` precisely to pass the
`deadline_at.date() < now.date()` hard filter and stay `open`. Once the clock passes 2026-12-31,
every one produces `reasons=['deadline_passed']`, `hard_filter_passed=False`, and the
`saved_count`/`filtered_count` assertions break **en masse** — even though production code is
correct. The whole green bar has a hidden expiry date.

**Recommendation:** Compute seed deadlines relative to an injected/frozen "now" (`now +
timedelta(days=365)`) rather than absolute literals; tie to the TEST-1 clock fix so code and
fixtures share one clock. **Effort: medium.** *(P0.)*

### 🟡 TEST-3 — Real OpenAI network clients (extraction, embeddings, explanations) entirely untested — `medium`
**Location:** `extraction/service.py:1464-1511`; `embeddings/service.py:71-88`; `explanations/service.py:80-112`

A grep for the OpenAI client classes / `httpx.post` across `tests/` returns nothing. The actual
`httpx.post` → `raise_for_status` → `response.json()['choices'][0]['message']['content']` /
`['data']` parsing has zero coverage. A schema change, a non-200, a refusal, or a truncated/empty
`choices` array would only surface in production. Mock the transport (respx / monkeypatch) for
success / non-JSON / error / 429 cases. **Effort: medium.** (See [EXT-3](04-llm-extraction.md).)

### 🟡 TEST-4 — CLI command handlers (the operational entrypoints) untested — `medium`
**Location:** `cli.py:32-451` (~15 `_cmd_*` handlers + `_build_parser` + `main`); tested: only the pure `_format_*` helpers

The actual command wiring — argument parsing, session lifecycle, service orchestration that
operators invoke daily — is never exercised. A broken subparser, a renamed service kwarg, or a
session/commit bug wouldn't be caught. The CLI is *how this tool is run in production*. Add a few
smoke tests that build the parser and invoke 2-3 commands end-to-end against the in-memory DB
(seed-sources, match, embed). **Effort: medium.**

### 🟡 TEST-5 — No test framework/coverage declared, and no CI — nothing enforces the green bar — `medium`
**Location:** `pyproject.toml` (no `pytest`/`coverage`/dev group); no `.github/workflows`

`poetry run pytest` fails (`No module named pytest`); the suite only runs via stdlib `python -m
unittest`. No CI anywhere. So nothing automatically runs the suite, no coverage is measured, and the
already-failing TEST-1 can rot unnoticed. Add `pytest` + `pytest-cov` to a dev group and a minimal
GitHub Actions job on push/PR; treat red as blocking. **Effort: small.** *(P0.)*

### ⚪ TEST-6 — Each connector fixture has exactly one record; multi-item/pagination/malformed parsing untested — `low`
**Location:** `tests/fixtures/*` (each yields 1 grant); `test_stage3_ingestion.py:319-322` asserts `len==1`
for every connector. No test for a multi-item listing, pagination/limit truncation, an item missing
fields mid-list, or a bad item that should be skipped while siblings succeed. A parser that crashes
on item N or drops valid siblings would pass today. Extend 1-2 fixtures (eu_funding, a WP-REST
source, a sitemap source) with multiple + one malformed item; assert count/ordering/limit and that
the bad item is skipped with a recorded error. **Effort: small.**
