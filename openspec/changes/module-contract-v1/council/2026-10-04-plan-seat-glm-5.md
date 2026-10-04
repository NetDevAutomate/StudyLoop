# Planning Council Response — Module Contract v1

**Seat**: glm-5
**Date**: 2026-10-04
**Proposal**: `openspec/changes/module-contract-v1/proposal.md`

---

## Q1. Lane shape

**Proposal alignment: 5 lanes is correct.** The DoD scope (items 1–7) splits naturally into:

1. **M1 – Verification API** – CLI + programmatic verification (`practice_verify`), `PracticeVerificationResult`, DB recording
2. **M2 – Schema enforcement** – `PracticeTask`, `PracticeVerification`, `PracticeDeck` Pydantic models with `extra: "forbid"`
3. **M3 – Mentor integration** – Evidence delivery, mentor PTY/ACP handoff, `AGENT_HINT.md` injection
4. **M4 – UI surface** – Web `/practice` endpoints, Alpine.js deck view, verification confirmation UI
5. **M5 – DoD validation** – Conformance rules (MC001–MC016), acceptance tier, DoD item checklist

**Divergence from proposal**: I recommend **collapsing M4 into M3** (mentor+UI as one lane). The evidence-to-mentor-to-UI path is a single interaction flow — the mentor needs the UI to show the deck, and the UI needs the mentor to observe practice attempts. Splitting them creates a coordination seam that buys nothing. M4 is the smallest lane (~300 LoC of Alpine/HTMX against ~800 LoC for M3) and shares the `expected_artifacts` / `evidence_prompts` seam with M3.

**Recommended 4-lane shape**:
- M1: Verification API (CLI + DB + result types)
- M2: Schemas (Pydantic models + `extra: forbid`)
- M3: Mentor + UI integration (evidence delivery, PTY/ACP handoff, `/practice` endpoints, Alpine deck)
- M4: DoD validation (conformance rules, acceptance tests, DoD checklist)

---

## Q2. Sequence

**M2 → M1 → M3 → M4** is the correct critical path.

**Rationale**:
1. **M2 first** because `PracticeTask`, `PracticeVerification`, `PracticeDeck` are the contract. The verification API (M1) and UI (M3) both consume these schemas. Without `extra: "forbid"` enforcement, downstream lanes accept malformed decks.
2. **M1 second** because CLI verification (`practice_verify`) is the primary user surface. The mentor integration (M3) needs a working `verify_practice_task` to record attempts and observations.
3. **M3 third** because mentor + UI depend on M1's verification result. The evidence delivery path (`expected_artifacts`, `evidence_prompts`) needs the `PracticeVerification` schema from M2.
4. **M4 last** because DoD validation is a check on the whole system. It needs M1's CLI, M2's schemas, and M3's mentor integration to exercise.

**Risk addressed by this sequence**: M2 first eliminates the "schema drift" risk where a lane accepts a deck shape that later breaks verification or UI rendering.

---

## Q3. Parallel windows

**M1 and M2 can overlap partially**. Once M2's `PracticeDeck` model lands (the first schema), M1 can start consuming it for `verify_practice_task` while M2 finishes `PracticeTask` and `PracticeVerification`. The schemas are small (3 models, ~150 LoC total) — the overlap is ~1 day.

**M3 cannot start until M1 completes**. The mentor integration needs `PracticeVerificationResult` and the observation recording path (`learning/practice.py:179-188`). Starting M3 before M1 risks re-implementing verification logic in the mentor path.

**M4 cannot start until M3 completes**. DoD validation needs the full `/practice` surface to exercise MC001–MC016. Starting M4 early creates a chicken-and-egg: the acceptance tests need a working practice flow to verify.

**Parallel opportunity**: M2's schema writing + M1's verification logic can proceed concurrently after `PracticeDeck` lands. The coordination point is the `PracticeDeck` model — once it exists, M1 can import it while M2 finishes the nested models.

---

## Q4. Critical-path items

**DoD items 5 and 7 are the longest poles**:

1. **DoD 5 – Mentor observes practice attempts** (estimated 4–5 days):
   - Requires PTY/ACP transport integration (`web/routes/session/_transport.py:42-103`)
   - Requires observation recording in `learning/practice.py:179-188` (confident/struggling)
   - Requires evidence collection (`expected_artifacts`, `evidence_prompts`)
   - Mentor PTY must see the learner's shell session and record observations in real-time
   - ACP path (Kiro CLI) needs `_build_acp_transport` factory with `KIRO_ACP_AGENT_NAME` resolution

2. **DoD 7 – Acceptance tier validates DoD** (estimated 3–4 days):
   - Requires new acceptance tests under `tests/acceptance/` with `STUDYLOOP_ACC=1`
   - Requires exercising MC001–MC016 conformance rules
   - Requires `just preflight` + `just test-acceptance` to pass
   - Test harness needs Playwright setup from `tests/e2e/_env.py` (F2)

**DoD 1–4 are smaller and not on the critical path**:
- DoD 1–2: Schemas + `extra: forbid` (1–2 days, M2)
- DoD 3: CLI `practice verify` (1–2 days, M1)
- DoD 4: Verification recording (1 day, M1, depends on `learning/practice.py:179-188`)

---

## Q5. Council schedule

**Divergence from proposal**: I recommend **2 checkpoints, not 3**:

1. **Checkpoint 1 (end of M2)**: Schemas landed, `extra: forbid` enforced, M1 verification logic in progress
2. **Checkpoint 2 (end of M4)**: Full DoD validated, `just preflight` + acceptance tests passing

**Rationale**: The proposal's 3-checkpoint schedule (after M2, after M1, after M4) adds coordination overhead for little value. M1 and M2 are small (combined 3–4 days) — a single checkpoint after M2 captures both. M3 and M4 are larger (combined 7–9 days) and have the critical-path mentor integration — a checkpoint after M4 confirms the DoD.

**Recommended schedule**:
- Day 3: Checkpoint 1 (M2 complete, M1 in progress)
- Day 12: Checkpoint 2 (M3 complete, M4 complete, DoD validated)

This reduces coordination overhead while still catching schema drift early (the M2 checkpoint).

---

## Q6. Risk surfacing

**R2 (mentor evidence collection) and R5 (ACP/PTY divergence) are the highest risks**:

1. **R2 – Mentor evidence collection**:
   - Evidence path requires `expected_artifacts` + `evidence_prompts` to be collected during practice
   - Learner might skip evidence steps, leaving the mentor without artifacts to observe
   - Mitigation: Make `evidence_prompts` a blocking checklist in the UI (learner must acknowledge each prompt before verification)
   - Detection: Add `missing_evidence` field to `PracticeVerificationResult` (already present in `learning/practice.py:282-290` as `missing`)

2. **R5 – ACP/PTY divergence**:
   - PTY path uses `shell=True` for deck commands (`learning/practice.py:282-290`)
   - ACP path uses structured JSON-RPC (`session/transports/acp.py:1-100`)
   - Risk: Evidence collection works in PTY but not ACP (or vice versa)
   - Mitigation: M4 acceptance tests must cover **both** transports (STUDYLOOP_TRANSPORT=pty + STUDYLOOP_TRANSPORT=acp body override)
   - Detection: Add transport-specific test in M4 (`test_practice_deck_acp_transport.py`)

**R8 (learner skips verification) is mitigated by DoD 6** (UI confirmation flow). The proposal's confirmation UI (`/practice` endpoints with Alpine.js) requires explicit "verification passed/failed" acknowledgement, preventing silent skips.

---

## Q7. Effort and critical path

**Estimated effort by lane**:

| Lane | Est. Days | Critical Path? | Notes |
|------|-----------|----------------|-------|
| M2 – Schemas | 1–2 | Yes (first) | Small, contract-first |
| M1 – Verification API | 2–3 | Yes (second) | CLI + DB + observation recording |
| M3 – Mentor + UI | 4–5 | Yes (third) | PTY/ACP transport, evidence delivery, Alpine UI |
| M4 – DoD validation | 3–4 | Yes (last) | Acceptance tests, conformance rules |

**Total calendar days: 10–14 days** (parallel M1/M2 overlap saves ~1 day).

**Critical path**: M2 → M1 → M3 → M4. No lane can start before its predecessor completes (except M1/M2 overlap after `PracticeDeck` lands).

**Divergence from proposal**: The proposal estimates 12–15 days. I estimate **10–14 days** because M4 is smaller than stated (acceptance tests use existing `tests/e2e/_env.py` harness from F2, not a new harness). The mentor integration (M3) is the longest pole at 4–5 days, not M4.

---

## Q8. Constraint adherence

**C1–C8 all satisfiable**:

- **C1 (branch naming)**: Use `feat/practice-module-v1` (not `lane/…`). The lane-ownership guard (`tests/_lane_ownership.py`) keys off `lane/m<n>-` patterns, so `feat/` is safe.
- **C2 (no lane/ branches)**: Confirmed by F4 (`tests/_lane_ownership.py:1-80`). The guard exists and will reject `lane/` branches.
- **C3 (fresh worktree per lane)**: F1 confirms `docs/contributing.md:61,74` requires `env -u VIRTUAL_ENV`. Each lane starts in a clean worktree.
- **C4 (preflight before merge)**: `just preflight` runs lint, typecheck, test, test-js, docs, release-consistency, spec-check (Justfile:279).
- **C5 (DoD acceptance tier)**: F3 confirms `docs/acceptance-testing.md` with `STUDYLOOP_ACC=1` marker.
- **C6 (no tests in PR body)**: Not applicable — tests go in `tests/acceptance/` and `tests/e2e/`, not the PR body.
- **C7 (DoD acceptance before merge)**: M4 validation includes `STUDYLOOP_ACC=1` tests running `just preflight`.
- **C8 (no v1.1 browser "Check progress")**: Deferred — not in DoD items 1–7.

---

## Q9. Cut-scope triggers

**Cut M3's ACP transport if**:
- Mentor PTY integration takes >5 days
- ACP-specific evidence collection diverges from PTY (R5 materialises)
- Kiro CLI `KIRO_ACP_AGENT_NAME` resolution fails in test harness

**Cut M4's acceptance-tier coverage if**:
- M3 slips to >6 days
- DoD items 1–6 pass manual validation but M4 tests fail on transport-specific edge cases

**Never cut**:
- M2 (schemas) — contract-first, everything depends on it
- DoD 5 (mentor observes practice) — core value prop, without it the module is a verification API only

**Cut order**: M4 acceptance-tier coverage → M3 ACP transport → M4 entirely (manual DoD validation). M2 and DoD 5 are non-negotiable.

---

**Critical path: 10 calendar days**

**Plan verdict: build as proposed** — with the 4-lane shape (M3 + UI collapsed) and 2-checkpoint schedule. The proposal's technical direction is sound; the sequencing is correct; the risks (R2, R5) are mitigable. The 10-day critical path is tighter than the proposal's estimate because M4 reuses the existing e2e harness.
