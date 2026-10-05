# Council M2 — release proof: arbitration (2026-10-05)

Three seats on one brief (`2026-10-05-m2-brief.md`), all tip-checked at `2506b82d`, all
read-only. Coordinator call written first (`catch-rate.md` row M2, 14:52). Seat files:
`2026-10-05-m2-seat-gpt-5.6-sol.md` (10 raised), `-glm-5.md` (6), `-qwen3-coder-next.md` (5).
Every finding below was checked against the tree before it was accepted or discounted.

## Verdict

**Release-ready pending owner steps.** All three seats reached that verdict independently and
agree on all seven item verdicts. Nothing v1.1/v2/stage-2/stage-3 leaks into the shipped
surface (three independent greps: no consent endpoint, no browser-side phase execution, no
view-only credential or grant, no `duckdb-database`, no index/registry code — the `registry.py`
hit is an adapter cache). The specs and the merged code agree on every M0/M1 ruling checked
(closed-write observability, ACP wedge/fail-fast, every-error-class teardown, allowlisted kind
environment, MC017).

## The seven DoD items (proposal §9) — on evidence

| # | Verdict | Evidence that carries it | Caveat / weakest point |
| --- | --- | --- | --- |
| 1 schema | **held** | `tests/test_module_schema.py` (incl. `test_proposal_example_deck_loads_through_load_practice_deck`, whose red `evidence/S/example-deck-extra-forbidden.red.txt` is an original red); merged `d2671ce8` | the other two S reds are labelled retrospective (S-review F1) |
| 2 `module check` | **held** | `modules/check.py` `RULE_IDS` MC001–MC017; `tests/test_module_check.py::test_rule_ids_are_mc001_to_mc017_in_table_order` + the broken/repaired pairs `fixtures/modules/mc001..mc017`; spec, CLI `--help`, docs and CHANGELOG all say seventeen | `design.md:132/137` and `tasks.md:45` still said sixteen — fixed in this arbitration commit |
| 3 runner | **held-with-caveat** | `tests/test_module_runner.py::test_drill_writes_no_observation`; `tests/test_module_drill_cli.py::test_scaffold_offline_drill_runs_setup_check_cleanup_end_to_end`; M1 arbitration | the DoD says "clean environment"; the M1 ruling (runner docstring, consent prompt, ADR-0012) is "consent-gated execution with hygiene, not a sandbox" — the caveat is the v1 threat model, stated to the learner, not a gap to close in v1 |
| 4 add + Labs | **held** | `modules/store.py` stage→check→digest→publish; `tests/e2e/test_module_labs_journey.py` 9 phases (re-run by two seats and the coordinator: 9 passed); `web/routes/modules.py` "no phase runs here" | per-commit gate tails for W do not exist (recorded gap) |
| 5 mentor delivery | **held** | `tests/integration/test_module_delivery_transports.py` (PTY + ACP, 10 tests) — recorded runs on merged main: `evidence/M2/integration-transports-on-main.txt` (10 passed at `a323bb11`, re-run 10 passed at `5438eb40`); lane T's own red transcripts carry the command on line 1 | the lane merge gates' `test` recipe deselects the integration tier (813–874 deselected in every gate), so until today no post-merge gate had run it — hence the recorded M2 run |
| 6 docs | **held** | `docs/module-contract.md` § "Adding a module"; `.github/PULL_REQUEST_TEMPLATE.md`; `tests/test_docs_drift.py` enrols the page's fenced commands | the drift test pins commands, not the checklist or the template (gpt F6): the brief overstated "pins" — corrected below, no new pin added (prose is human review by the contributor guide's own rule) |
| 7 kdrill | **not held — by design** | `tests/acceptance/test_module_kdrill_live.py` exists, skips cleanly without `STUDYLOOP_ACC=1 STUDYLOOP_LIVE=1`; K0 (`modules/cluster.py`) merged `d997a4d0` makes it runnable; MC017 and the `module check . --json` command are in the #53 draft | `evidence/kdrill/` does not exist; K1 (Bruno's converted module at a frozen sha passes `module check`) and K2 (owner's live run) are owner steps |

## Findings — verified, acted, discounted

**Acted in this arbitration commit (coordinator edits):**
- gpt F9 / glm (Q1 item 2) — `design.md:132` "16 single-fault fixtures" → 17; `design.md:137` and `tasks.md:45` "MC001–MC016" → MC017. Verified stale; fixed.
- gpt F5 / glm F3 / U1-F1 — the hash-pinned UAT rubric named `server.log` and `attempt-envelope.json`. Verified. Per `uat/rubric.py`'s own rule (edits = a new version; the loader rejects an edited-in-place file by hash) the fix is **`module_rubric_v2.md`** with the shipped member names (`server-log.txt`, `labs-binding.json`, `practice-envelope.json` when a phase ran) and the corrected missing-`kind` prompt (design.md §6 step 7), registered in `module_rubric_registry.json`; v1 kept and still pinned. Both versions load (`load_rubric`), the rubric test passes.
- gpt F10 — the #53 draft (`comms/2026-10-04-issue-53-reply.md`) said only the schema was live and carried no MC017 note. Verified. Rewritten to the shipped surface with the MC017 paragraph and the `studyloop module check . --json` command (verified against `--help`). **Still not posted — owner's.**
- gpt (item 5 weakest) — the integration transcript named an older tip. Re-run on the arbitration tip and recorded (10 passed).
- gpt F6 — the brief claimed the drift test "pins" the checklist and PR template; it enrols fenced commands only. Verified; the claim is corrected here. No new pin: the contributor guide's own rule is that prose truth is human review (`contributing.md` strict-build/drift/prose distinction, G1 fix 5).

**Accepted as recorded gaps / caveats (no action in v1):**
- gpt F1 — DoD 7 not held: owner/Bruno steps K1/K2 (the only BLOCKER; by design).
- gpt F2 / glm F6 / qwen GAP1 — "clean environment" vs "hygiene, not a sandbox": caveat, documented in three places by the M1 ruling; OS sandboxing is a tracked v2 follow-up.
- gpt F3 / glm Q5 — U2 owner sign-off not run (U2-ready since `79dab398`).
- gpt F4 / glm F4 / qwen GAP5 — per-commit gate tails absent for U1 (and W): recorded in `evidence/U1/README.md`; not backfilled.
- gpt F7 / glm F5 / qwen NOTE1 — K0-F8 (live cap on core's `kind` output): tracked follow-up in `tasks.md`.
- gpt F8 — the lane `merge-gate.txt` files are gate-script summaries (no command on line 1 by construction); they are attestations whose per-recipe logs lived under the gate's temp directory. Accepted as a labelling point: future gate scripts should copy the per-recipe tails into evidence (follow-up, recorded in `tasks.md`).
- glm F2 — integration tier never ran in a post-merge gate until M2: true; closed by the recorded M2 runs; follow-up recorded to add `-m integration` to the gate script.

**Discounted (checked and false, or not a finding):**
- glm F1 — "no red transcript for the first schema test": false. `evidence/S/example-deck-extra-forbidden.red.txt` is the original red for exactly that test; the two labelled retrospective reds are the other S tests (S-review F1, already recorded).
- qwen GAP2 — "testacc did not run `test_module_delivery.py`": a unit file is not an acceptance test; the tiers are distinct by design.
- qwen GAP4 — "prose may drift": restated gpt F6 without the specific claim; folded into F6.
- qwen Q4 citations — the kind env allowlist is `modules/cluster.py:109` (`KIND_ENV_ALLOWLIST`), not `runner.py:212-240`; "wedge/fail-fast" is the ACP transport, not runner argv errors. qwen NOTE5 — personas "22 passed / 1 xfailed" is stale (41 passed, 0 xfail on the tip). qwen Q5 — a K2 that "provisions clusters on AWS/GCP/Azure" is invented (K2 is the owner's local kind run). qwen Q6 — ledger totals (84/79/76/5) match nothing in the ledger. Weight: item-verdict confirmation only.

Totals: **21 raised** (gpt 10, glm 6, qwen 5) / **15 verified** / **5 acted** in this commit + **7 accepted as recorded gaps or caveats** / **6 discounted** (glm 1, qwen 5 — qwen's own findings beyond the verdict table did not survive checking; it read the right tree, which is what the M1 ruling asked of it).

## Before the change is archived (`tasks.md` 4.1) — owner steps, exactly

1. `git push origin main` (local `main` is ~230 commits ahead of origin; every merge commit names its review and gate).
2. Post the #53 reply from `comms/2026-10-04-issue-53-reply.md` (rewritten today; fill the pushed sha).
3. Settle the uncommitted `agents/kiro/study-plan-architect.json` / `agents/kiro/studyloop.json` diff (a shell deny list containing a bare `"*"`): commit, fix or discard.
4. U2: `just testuat` — both personas twice against `module_rubric_v2.md`; record the sign-off under `evidence/uat/`.
5. K1: Bruno's converted `studyloop-module-kubernetes-drills` at a frozen sha passes `studyloop module check . --json`; store the report under `evidence/kdrill/`.
6. K2: the live kdrill drill on the owner's machine (docker, kind, kubectl present; `STUDYLOOP_ACC=1 STUDYLOOP_LIVE=1`): setup, check, cleanup complete, the `studyloop-*` cluster gone, the sentinel cluster intact; store the log under `evidence/kdrill/`.
Coordinator follow-ups recorded in `tasks.md`: K0-F8; gate script to run `-m integration` and copy per-recipe tails into evidence; `module_rubric_v1.md` superseded by v2.

## Catch-rate (Q6)

The ledger before M2: eight review rows, 75 raised / 65 verified / 58 acted (+4 explicit v1 rulings) / 10 discounted. gpt-5.6-sol's lane seat verified 45 of 46 and was right to block W, K0 and U1 — each block found failure-path or evidence-honesty defects the coordinator's own call had missed. DeepSeek stays dropped (two fabrications, zero citations). GLM confirms and occasionally adds one true point (M1's redaction-order bug); Qwen now reads the right tree but its additions still do not survive checking. **Ruling:** one gpt-5.6-sol seat per lane merge earned its cost and continues; full councils stay reserved for contract boundaries (M0/M1/M2-class decisions) with three seats, and a seat whose additions are discounted twice running is not re-seated for symmetry.
