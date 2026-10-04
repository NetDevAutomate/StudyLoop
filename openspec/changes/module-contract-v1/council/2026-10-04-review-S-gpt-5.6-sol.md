# Lane S independent merge review

## 1. Red first

**S1.** Explicit branch resolution is covered by `test_mapped_feat_branch_resolves_to_its_lane` and `test_fixture_branch_map_matches_design_and_points_at_real_lanes`; unmapped branches by `test_unmapped_branch_is_none_not_an_error`; legacy fallback and malformed names by `test_legacy_lane_branches_still_resolve_when_a_map_is_supplied` plus the pre-existing branch tests; cross-lane rejection and owner acceptance by `test_mapped_lane_editing_another_lanes_file_fails` and `test_mapped_lane_editing_its_own_file_is_ok`. No S1 red transcript exists under `evidence/S/`: finding 1. Also, no test proves the promised map-before-regex precedence using a mapped `lane/m…` name: finding 2.

**S2.** The six-field acceptance path is covered by `test_proposal_example_deck_loads_through_load_practice_deck`; aliases/serialization and JSON-schema visibility by the round-trip/schema tests; optional ids, defaults, old-deck compatibility and unchanged `extra: forbid` by the compatibility tests; slug validity and per-deck task-id uniqueness by the id tests; the closed scaffolding enum and schema-level MC010 permissiveness by the final tests. `evidence/S/example-deck-extra-forbidden.red.txt` is a valid red for the proposal example: it shows all six new inputs rejected before implementation. It contains only the first test, however; the remaining added behavior tests have no saved failing transcript, including the duplicate-id, malformed-id and closed-enum constraints: finding 3 under the merge brief’s explicit “any test with no red transcript” rule. The coordinator’s evidence-only call is therefore incomplete, not merely missing S1 evidence.

## 2. Ownership

Against `design.md` §2 and `S-schema.md` owned globs:

- `openspec/changes/module-contract-v1/evidence/S/example-deck-extra-forbidden.red.txt` — **owned** (lane brief’s evidence glob).
- `packages/studyloop/src/studyloop/content/schemas.py` — **owned**.
- `packages/studyloop/tests/_lane_ownership.py` — **owned** (also matched by the existing shared test glob).
- `packages/studyloop/tests/fixtures/lane_ownership.yaml` — **owned** (also guard-shared).
- `packages/studyloop/tests/test_lane_ownership.py` — **owned** (also guard-shared).
- `packages/studyloop/tests/test_module_schema.py` — **owned** (also guard-shared).

No outside file and no docs path is in the reviewed diff. The C/R/T/W glob transcription matches `design.md` §2, including brace expansion and W’s `web/app.py` note.

## 3. Scope

The diff is confined to S1 guard re-keying and S2’s six additive fields plus their stated id invariants. `SLUG_PATTERN`, `SlugId`, and `ScaffoldingLevel` are reasonable local type aliases, not registry machinery. There is no runtime dependency, registry/catalogue shape, pragma/allowlist, `--no-verify`, `SKIP=`, hook edit, `.pre-commit-config.yaml` edit, or `.secrets.baseline` edit. No scope or ownership finding.

S1’s `just preflight` result is **UNVERIFIED** from the supplied transcript. The currently running tip `just preflight` and `just e2e` are also **UNVERIFIED** and remain coordinator merge gates, not review findings.

## 4. Next lane C

1. `packages/studyloop/src/studyloop/content/schemas.py`: C’s MC014 dependency is the exact `SLUG_PATTERN` / `SlugId` contract and the optional `PracticeDeck.id` / `PracticeTask.id` fields. `ScaffoldingLevel` is not an MC014 dependency; the coordinator’s risk list is wrong on that point (it may matter to MC010 only).
2. `packages/studyloop/tests/fixtures/lane_ownership.yaml`: C depends on the new top-level `branches` mapping and the already-expanded `C` globs. C must receive S before its gate and must not extend this S-owned fixture itself; any missing C path requires coordinator/S ownership handling.

## Verdict: merge after fixes

1. `packages/studyloop/tests/test_lane_ownership.py:153` — S1 has no red transcript. **Fix:** add honest pre-implementation evidence for the branch-map behaviors, explicitly labelled retrospective if reconstructed.
2. `packages/studyloop/tests/_lane_ownership.py:56` — map-before-regex precedence has no test. **Fix:** add a case whose mapped legacy-shaped branch resolves to the explicit map value.
3. `packages/studyloop/tests/test_module_schema.py:137` — S2 tests after the proposal-example test have no saved red transcript. **Fix:** add pre-implementation reds per added constraint/behavior group, labelling any reconstruction.

Findings: 3 raised
