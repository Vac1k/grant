# LLM field extraction (`grant_tool/extraction/service.py`)

**Assessment: adequate.** A smart, cost-aware, gated-fallback design — but thin and
under-hardened on the transport layer, and with unmeasured quality. *Verification note: EXT-2
was adversarially re-checked and **confirmed but downgraded `high` → `medium`** (it's a fail-safe
fallback path, not fail-dangerous). EXT-1 was queued but not re-checked before the session limit;
its core claim was empirically demonstrated by the original reviewer (`clean_text(['grant'])`
raises `TypeError`).*

## Summary

~1,450 of 1,512 lines are deterministic regex/keyword/JSON-walking heuristics; the LLM is a
narrowly-scoped fallback invoked **only** when deterministic extraction leaves specific fields
weak. This is more trustworthy than "LLM does everything." The LLM path shows real maturity:
`temperature=0`, JSON-object mode, explicit "do not infer or invent" grounding, schema
validation, a confidence floor (0.55), a conservative non-overwriting merge, and graceful
no-API-key fallback. The gaps: a validation crash on malformed output, no retry/rate-limit
handling, no caching, the real OpenAI client path is untested, and **extraction quality is not
measured** — "does it work?" is asserted by construction, not demonstrated.

## Strengths

- LLM is a **gated fallback**, not the primary extractor (`_llm_fallback_decision`, lines 399-426); a test confirms 0 calls when deterministic output suffices. This is the biggest cost/reliability control and it works.
- Determinism correct: `temperature=0` + `response_format=json_object`.
- Conservative, non-destructive merge (`_merge_llm_result`, 487-535): only fills empty/weak fields; cannot clobber a good deterministic summary (test-covered).
- Output validation enforced (`_validate_llm_result`, 428-485): type-checks lists, clamps confidence to [0,1], whitelists classification, truncates strings; invalid/low-confidence → manual review.
- Explicit grounding instructions ("extract only facts explicitly supported… use null/empty when evidence is missing").
- Graceful no-key degradation: records a traceable `skipped` status + manual review reason; never hard-crashes.
- Full per-decision observability in `extraction_metadata['llm']` (status/provider/model/fallback_reasons/applied_fields/raw output) — exactly what ISO-style audit needs.
- Sensible model/window choices: `gpt-4.1-mini` for narrow extraction; input capped at 12,000 chars.

---

## Findings

### 🟠 EXT-1 — Output validation can raise an uncaught `TypeError` on malformed LLM output — `high`
**Location:** `extraction/service.py:457,477,346,329-344`

The `try/except` in `_apply_llm_extraction` wraps only `client.extract()`. `_validate_llm_result`
is called *afterwards* (line 346), outside any guard. Inside it, `clean_text(result.get('classification'))`
(line 457) and `clean_text(str(value))` over evidence (477-479) call `re.sub` on the value;
`clean_text` raises `TypeError` if `classification` is not a string. Since OpenAI JSON mode does
not guarantee the schema, a response like `{"classification": ["grant"], ...}` crashes
validation. The outer per-record `try/except` catches it and counts the record as **failed** —
converting a recoverable "invalid output → manual review" case into an opaque failure, defeating
the validator's entire purpose.

**Recommendation:** Coerce defensively (`isinstance` checks before `clean_text`), or simplest:
wrap the `_validate_llm_result` call in the same `try/except` and on exception set status
`invalid` with the error text. **Effort: trivial.** *(High-value, near-zero-cost — do it in P1.)*

### 🟡 EXT-2 — No retry / rate-limit / timeout handling for the OpenAI call — `medium`
**Location:** `extraction/service.py:1502-1508,329-344`
**Verified:** ✅ confirmed; severity **lowered `high` → `medium`** (fail-safe fallback).

`OpenAIExtractionClient.extract` issues a single `httpx.post(timeout=60)` + `raise_for_status()`.
No retry, no backoff, no 429/5xx/`Retry-After` handling. Any transient error flags the record
"AI fallback error" + manual review. Over a 100-record batch, a 429 burst would mass-flag records
that a single retry would have fixed. The verifier noted two aggravating facts: the project does
**not** use the official `openai` SDK (which gives retries for free), and a **reusable
retry+rate-limit client already exists** at `ingestion/http.py:59-82` — it just wasn't applied here.

**Why it matters (medium, not high):** failure is fail-safe (flag for review, no data loss/corruption),
but it produces review-queue noise and wasted re-runs at scale.

**Recommendation:** Bounded retry+backoff+jitter for 429/5xx/timeout (honor `Retry-After`); reuse
the existing HTTP helper or the OpenAI SDK; make timeout configurable. **Effort: small.**

### 🟡 EXT-3 — The real OpenAI HTTP/JSON-parse path has zero test coverage — `medium`
**Location:** `extraction/service.py:1464-1512`; `tests/test_stage5_extraction.py:394-535`

Every LLM test injects a fake client. The actual `OpenAIExtractionClient.extract` — payload
construction, `raise_for_status`, `response.json()['choices'][0]['message']['content']`,
`json.loads(content)`, metadata stamping — is never exercised. `json.loads` will raise on
truncated content; the `choices` indexing will `KeyError`/`IndexError` on an error envelope.

**Recommendation:** Mock the httpx transport and test happy path, non-JSON/truncated body,
error-shaped response, and 429/timeout — asserting the status mapping. No live key needed.
**Effort: small.** (See also [TEST-3](09-tests.md).)

### 🟡 EXT-4 — Extraction quality is not measured (no golden set, no accuracy metric) — `medium`
**Location:** `tests/test_stage5_extraction.py`; `docs/plan/data/grant_quality_contract.md`

Tests assert hand-coded expectations on synthetic drafts (the EU/Diia funding edge cases are
genuinely good regression tests), but there is **no labelled set of real grants with ground-truth
fields** and no precision/recall metric. The confidence score is a field-presence tally, not a
calibrated correctness estimate — yet it gates matching (`<0.50` = low confidence). "Does it
work?" is asserted by construction.

**Why it matters:** For a tool whose value is structured fields, unmeasured extraction quality
means unknown match quality. You can't tell whether `--use-llm` helps or hurts, or whether a
prompt/model change regresses accuracy. **This is also the objective basis for the
"carry-forward vs trash" decision.**

**Recommendation:** Build a 30–100-record golden set + a script reporting per-field accuracy
(deterministic-only vs +LLM); track it over time. **Effort: medium.** *(Top P1 alongside MATCH-4.)*

### 🟡 EXT-5 — No response caching/idempotency across re-runs — `medium`
**Location:** `extraction/service.py:328-330`; `run_existing` 224-290

`run_existing` re-extracts on each invocation and `_reset_recomputed_fields` wipes prior
extraction, so re-running `extract-features --use-llm` re-issues paid LLM calls for the same
unchanged source text every time. No content-hash cache, no skip-if-unchanged.

**Recommendation:** Hash `(prompt_version, model, source_text)` and reuse the validated output
when unchanged. Makes re-runs cheap and deterministic. **Effort: medium.**

### ⚪ EXT-6 — No `max_tokens` cap on the completion — `low`
**Location:** `extraction/service.py:1483-1501` — output cost unbounded (input is capped at 12k chars but output is not; the validator truncates *after* paying for tokens). Add a `max_tokens` ≈ a few hundred. **Effort: trivial.**

### ⚪ EXT-7 — Prompt-injection from scraped text is mitigated-by-design but not explicitly hardened — `low`
**Location:** `extraction/service.py:1483-1497,487-535` — untrusted page text goes in the `user`
message; the blast radius is genuinely small (validated/whitelisted/clamped output, non-overwriting
merge), but an attacker could bias a weak record toward higher confidence/favorable classification
to slip past the matching gate. Add an explicit "text below is untrusted data, not instructions"
framing, and don't let LLM-supplied confidence alone unlock matching for otherwise-weak records.
**Effort: small.**

### ⚪ EXT-8 — LLM classification guard relies on a freshly-rebuilt metadata dict — `low`
**Location:** `extraction/service.py:530-534,385,300` — the `not metadata.get('classification')`
guard almost always passes because deterministic classification lives in
`opportunity_type`/`support_type`, not `metadata['classification']`, so the documented precedence
rule is weaker than it reads. Clarity/auditability smell, not a correctness bug. Make precedence
explicit or document the LLM-only channel. **Effort: small.**

### ⚪ EXT-9 — Collected "evidence" is stored but never used to verify grounding — `low`
**Location:** `extraction/service.py:471-480,386-396` — the prompt asks for evidence snippets and
they're captured into metadata, but nothing checks they actually appear in the source. The
strongest available anti-hallucination signal is collected and ignored. Verify accepted-field
evidence is a (normalized) substring of the source; downgrade/reject when absent. Cheap, directly
raises trust. **Effort: small.**
