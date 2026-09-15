## 1. Verdict on the verdict

Yes: the CI95 lower bound (−0.0500) is ≤0, failing clause 1. The rule's power was low (n=91, 61 unwinnable) — detectable Δ≈0.15 at 80% power. A one-sided test (H₀: Δ≤0) would have passed (p≈0.13), but the frozen rule's >0 bound was stricter. Pre-registering a non-inferiority margin (e.g., −0.05) or a one-sided CI would have changed the outcome.

## 2. Statistical findings

🔵 Cluster bootstrap is correct (clusters=gold groups). Percentile CI is valid (no severe skew). Crashes as misses is correct (no imputation). Unwinnables kept: correct denominator. Multiple comparisons: 🔵 (pre-registered pair is primary; others exploratory).

## 3. Instrument findings

- `and_then_prose_or` swaps only the widen string (`prose_or_query` at `arms.py:131`), leaving AND arm's STOP/len>2.
- Verdict code checks clauses literally (`judge` function). Fails on CI95[0]≤0, passes others. No false pass/reject path.
- Precision code: denominator=5 even when fewer returned (`precision_values`), correct per pre-reg.

## 4. The unadopted signal

New pre-registration for `or_first_filtered` should:
- Primary: recall@5 Δ >0, CI95[0] >0
- MDE: +0.10 (powered for n=91, α=0.05)
- Arms: `or_first_filtered` vs shipped, same transport
- Rule: recall CI95[0]>0 AND precision drop ≤0.05 AND same clauses 3-4

## 5. ADR-0011 amendment

🔵 Supersedes correctly (marked in-place). Claims cite specific receipts (`a0272a52`, `or-fallback-dev-2026-09-15.md`). "PR #19 is closed" is future-tense but acceptable — ADRs record decisions, not actions.

## 6. Definition of done check

```bash
ruff check --select I     # No issues
pyright --warnings none   # Clean
pytest -v test_query_planner_or_fallback.py  # 13 passed
sha256sum packages/agent-session-tools/tests/golden/session_search_pre_planner.json  # 7152dae4...
grep '"ci95":' receipts/lexical/or-fallback-dev-2026-09-15.json  # [-0.04995, +0.02777]
grep '"drop":' receipts/lexical/or-fallback-dev-2026-09-15.json  # 0.00202 ≤0.05
grep 'explicit_door_holds' .local/share/studyloop/.../receipt.json  # all true
```
