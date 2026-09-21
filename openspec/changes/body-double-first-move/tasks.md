# Implementation Tasks — the body double's first move (#30)

TDD, as the programme's items were: the RED is committed before the production
edit; each task has a definition of done a reviewer can tick from output.

- [x] **T1 RED** `f43f7eb2` — eleven tests: engine (`test_body_double_carries_one_passive_first_move_on_the_deferred_milestone`,
      `..._names_the_lesson_when_the_content_index_resolves_it`, `..._survives_a_broken_content_index`),
      CLI (`test_cli_now_prints_the_first_move_beneath_the_sit_with_door`), Today card
      (`tests/js/today-panel-plan.test.js`: `firstMoveNote`, hand-off detail), Body Double view and card
      markup (`tests/test_web_body_double_first_move.py`, static pins — `components.js` has no node harness),
      docs (`test_docs_plan_integration_contract.py`, two tests). All red for the stated reason.
- [x] **T2 GREEN** — `_lesson_title_for`, `_first_move`, the reason tail and `metadata["first_move"]`;
      `cli/_now.py` `First move:` line; `today-panel.js` `firstMoveNote` + `firstMove` in the hand-off;
      `components.js` listener + `firstMove: ''`; `index.html` `#bd-first-move` and `.today-first-move`;
      both guides. DoD: the eleven RED tests green; `test_now_plan_guidance.py` + `test_learning_decision.py`
      green; golden `ec451ce8` unchanged; JS 21/21; ruff, pyright, mkdocs `--strict` clean.
- [x] **T3** Read cost of the lesson lookup measured on the live host with the FTS index present, recorded
      in `design.md` (861 ms cold / 45–58 ms warm per concept, body-double path only).
- [ ] ⚖ **T4** Council review (three seats) of the RED and the GREEN; arbitration; one commit per accepted
      finding.
- [ ] **T5** Rubric row **3c** added to `docs/architecture/plan-integration/receipts/now-rubric-2026-09-16.md`:
      row 3's world emitted from the GREEN tree through both real collectors, the first move shown as
      emitted; verdict `PENDING` until the owner scores it. The change is archived only after the row is
      scored **yes**.
- [ ] **T6** CHANGELOG `[Unreleased]` entry; PR; CI green; fast-forward `main`; archive this change;
      ships in 0.5.1.
