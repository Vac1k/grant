# Code quality & maintainability

**Assessment: adequate** — competently structured for a solo+AI MVP, but two things would make a
second engineer uncomfortable: **no logging anywhere** and two very large central modules. *No
code-quality finding was re-verified by a second agent (none were re-checked before the session
limit; CQ-1 was the only `high`).*

## Summary

Consistent naming, modern Python 3.12 typing (`X | None`, `StrEnum`, frozen slotted dataclasses),
near-complete type-hint coverage, and clean repository/service separation. The data-quality
contract and normalization layers are well-organized and well-tested. The two biggest weaknesses
for a production carry-forward: (1) the `logging` module is used in **0 of 67 files**, so errors
are stringified into job metadata, printed in the CLI, or silently swallowed; and (2) the central
`extraction/service.py` (1,512 lines) concentrates very high complexity with confusing repeated
`metadata` reassignment and duplicated helpers. No critical correctness defects in the reviewed
code, but the duplication, zero docstrings, and broad `except Exception` raise maintenance cost.

## Strengths

- Modern, consistent typing throughout; near-complete signatures; `@dataclass(frozen=True, slots=True)` value objects.
- Clean architecture seams; the data-quality contract is a pure, side-effect-free evaluator that's easy to unit-test.
- Quality contract + normalization readable and pinned by explicit tests; parameterized via a dataclass rather than hardcoded.
- `Decimal` used consistently for money and confidence with explicit `quantize`/`ROUND_HALF_UP`.
- Good naming discipline and small single-purpose private helpers in the contract/normalization modules.
- No TODO/FIXME/HACK debt markers and no commented-out dead code in the focus files; clean argparse CLI.

---

## Findings

### 🟠 CQ-1 — No structured logging anywhere in the codebase — `high`
**Location:** entire `grant_tool/` package (0 of 67 files import `logging`); errors swallowed at `extraction/service.py:267-270`, `connectors/diia_business.py:44-45,59-60,84-85`

Errors are handled three ways: stringified into a list stored in `job_metadata`
(`errors.append(f"{grant.id}: {exc}")`), written into a metadata dict, or **silently swallowed**
with `except Exception: pass`. The only user-visible output is `print()` in the CLI. In the Celery
worker and FastAPI web paths there is no log output at all.

**Why it matters:** For a tool whose core job is scraping flaky sources and calling an LLM,
observability is essential. When ingestion silently drops a record or an extraction row fails,
there is no log, stack trace, or correlation id — only a truncated string buried in DB metadata
(`errors[:20]`). Diagnosing a production incident would require database archaeology. **The single
biggest operational gap for carrying the MVP forward.**

**Recommendation:** Add `logger = logging.getLogger(__name__)` per module; `logger.exception(...)`
at every `except`; configure handlers in `main.py`/`celery_app.py`; replace silent
`except: pass` with at least `logger.warning`. **Effort: medium.** *(P1.)*

### 🟡 CQ-2 — `extraction/service.py` is a 1,512-line module with confusing state-threading — `medium`
**Location:** `extraction/service.py:140-222` (`enrich_draft`), `:292-397` (`_apply_llm_extraction`, 108 lines), `:1037-1132` (`_parse_funding`, 97), `:827-903` (`_extract_funding`, 78)

`enrich_draft` sequences 10+ mutating steps and reassigns `metadata` three times (lines 149, 191,
199) while `_apply_llm_extraction` independently rebuilds and reassigns `draft.extraction_metadata`.
The funding path is a dense web of conditional branches.

**Why it matters:** The most central module is the hardest to onboard onto; the metadata-reassignment
shuffle is exactly the state-threading that breeds subtle bugs (a future edit that forgets to
re-read `draft.extraction_metadata` would silently lose fields).

**Recommendation:** Split the funding subsystem and the LLM fallback into their own units; make
`enrich_draft` operate on a single explicit metadata object passed by reference; add docstrings on
the pipeline order. **Effort: large.** (Pairs with [ARCH-3](06-architecture.md).)

### 🟡 CQ-3 — Duplicated helpers and a copy-pasted currency vocabulary — `medium`
**Location:** `_set_field_evidence` identical in `extraction/service.py:1442-1454` & `normalization.py:368-379`; `_merge_list` near-identical; `_decimal` in 3 places; the currency/money regex hand-copied across `extraction/service.py:1101,1151,1166,1178` + `normalization.py:21-46` + `utils.py:286-289`

**Why it matters:** These are the project's money- and evidence-recording primitives. Duplicated
currency vocabularies **will** drift — a fix to one regex silently fails to apply to the others,
producing inconsistent parsing between the deterministic extractor and the normalizer.

**Recommendation:** Move shared helpers into one module; centralize the currency token list +
money-detection regex into one constant/function reused everywhere. **Effort: medium.**

### 🟡 CQ-4 — Repository writers use `**fields: Any` with runtime `hasattr` validation — `medium`
**Location:** `repositories.py:934-981` (`upsert_grant`), `:1002-1008` (`update_grant_features`), + 4 more

Six write methods accept `**fields: Any` and validate via `if not hasattr(...): raise ValueError`
then `setattr`. The accepted field set/types/required-ness are invisible to callers and the type
checker; a typo or wrong-typed value is caught only at runtime (or not at all). For a persistence
layer this is the riskiest place to lose typing. Define explicit keyword params (or a `TypedDict`)
for common write fields; at minimum centralize the `hasattr`/`setattr` loop. **Effort: medium.**

### ⚪ CQ-5 — Five near-identical `metadata['llm'] = {...}` blocks in `_apply_llm_extraction` — `low`
**Location:** `extraction/service.py:302-326,332-344,349-364,368-383,386-396` — ~80 lines of repetitive
dict assembly for the skipped/no-key/error/invalid/low_confidence/success outcomes. Adding a key means
editing five blocks. Introduce a `_record_llm_outcome(...)` helper. **Effort: small.**

### ⚪ CQ-6 — Dead parameter `raw_html` threaded through three layers then `del`-ed — `low`
**Location:** `extraction/service.py:625` (`del raw_html`), plumbed via 133, 151, 256 — misleads readers
into thinking HTML feeds combined-text extraction (it doesn't). Remove the parameter and the `del`.
**Effort: trivial.**

### ⚪ CQ-7 — Zero docstrings on the six largest modules; undocumented magic constants; a refactor-trap helper — `low`
**Location:** the six focus files (0 docstrings each); magic numbers at `extraction/service.py:1378-1398,1126`; `contract.py:646`

Non-obvious heuristics are unexplained (confidence increments, the `< Decimal('10000')`
no-currency rejection, the 80-char text minimum). `_has_only_soft_warnings` is implemented as
`any(flag not in hard_flags ...)` — by name it should mean "all flags are soft" but returns True if
*any* is soft; it only works because the preceding `elif` chain already excluded hard flags. **A
refactor trap:** reordering that chain would silently promote `NEEDS_REVIEW` grants into matching,
with no test guarding the implicit pre-filter. (Trivium's org rules require documenting non-obvious
decisions for auditability.) Add docstrings; comment/reimplement the helper to be self-contained;
promote magic numbers to named constants. **Effort: small.**

### ⚪ CQ-8 — Broad `except Exception` to coerce/swallow + four hand-rolled `walk()` closures — `low`
**Location:** `extraction/service.py:1247,1460,331`; duplicated walkers at `:667,910,953,1207` — bare
`except Exception` on Decimal parses can mask genuine bugs (compounding CQ-1); the recursive
payload-traversal is reimplemented four times. Narrow to `(InvalidOperation, ValueError)`; extract one
generic `walk(value, visit_fn)`. **Effort: small.**
