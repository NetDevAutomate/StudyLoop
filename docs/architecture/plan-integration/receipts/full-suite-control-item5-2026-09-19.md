# Full-suite matched control — item 5 (D-F) — 2026-09-19

Two full `packages/studyloop/tests` runs in parallel, same machine, same
sandbox, `-q -p no:cacheprovider -rfE`:

| Tree | Worktree | Result |
| --- | --- | --- |
| **item 5** (`feat/energy-demand-body-double`, RED `ef319a7b` + GREEN working tree) | `studyloop-wt/item5` | 30 failed, **5126 passed**, 4 skipped, 804 deselected, 14 errors (10:17) |
| **control** (`main` `4f8e3e0f`, detached) | `studyloop-wt/ctrl-item5` | 30 failed, 5120 passed, 4 skipped, 804 deselected, 14 errors (10:24) |

Both worktrees were `uv sync --all-packages --group dev` and each proved to
import `studyloop` from its own tree before the run.

## Sorted failing-id sets

- item5 ∖ control = **∅** — zero regressions.
- control ∖ item5 = **∅** — nothing item 5 fixed by accident, and the six
  new tests account for the passed-count difference (+6).
- item5 ∖ committed environmental set (`full-suite-control-item4-2026-09-18.md`,
  44 ids + item 4's seven then-REDs) = **∅**. The seven ids on the other side of
  that comparison are item 4's REDs, green since `82293293`.

The 44 shared ids are the sandbox-environmental set the item-4 receipt lists
by name (journeys world guards, acceptance isolation, second-brain CLI/doctor,
harness-matrix live mechanics, obsidian vault isolation, fresh-install scope);
unchanged here, byte for byte.

## Scoped gates on the same tree

- `test_now_plan_guidance.py` 46/46 (six REDs flipped; golden `now_plan_no_active.json` byte-identical);
  `test_learning_decision.py` 5/5 (one stub updated to the starter's new keyword).
- JS `node --test packages/studyloop/tests/js/*.test.js` 144/144 (+5).
- e2e `test_journey_study_plan.py` + `test_plans_api.py` 20/20 (browser).
- `test_docs_plan_integration_contract.py` + `test_ci_workflow_contract.py` 39/39.
- `mkdocs build --strict` exit 0; `openspec validate plan-integration-followons` valid.
- ruff check / ruff format --check / pyright: clean on every touched file.

## Re-run after council review 7 (tree `3eb31f2d`, corrections F1–F7 landed)

| Tree | Result |
| --- | --- |
| **item 5 final** (`3eb31f2d`) | 30 failed, **5146 passed**, 4 skipped, 804 deselected, 14 errors (6:17) |
| **control** (`main` `4f8e3e0f`, same worktree as above) | 30 failed, 5120 passed, 4 skipped, 804 deselected, 14 errors (6:13) |

item5 ∖ control = **∅**; control ∖ item5 = **∅**; item5 ∖ committed environmental set = **∅**. The +26 passed are
the review-7 tests (F1's seven parametrisations, F2's two, F3's two, F4's five plus the capability matrix's three,
F5, the ready-plans-only test, and the F7/label JS pins run separately: 147/147).
