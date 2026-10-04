# Lane W — Labs entry, registrations, journeys, assembly

**Do not start before wave 1.** W1 (tests only) begins after S has merged and M0 has decided;
W2–W5 begin only after C, R (post-M1) and T have merged. This file exists so the lane's scope
is fixed before the others start, not so it can begin.

Read `00-common.md` first. Then `proposal.md` §8 (the Labs surface; what is **not** in v1:
browser Check progress, automatic checks), §5.6 (no learner-facing hint/solution surface),
`design.md` §2–§6 (Persona A and B), and `docs/acceptance-testing.md`.

| | |
| --- | --- |
| Branch | `feat/module-web-labs` |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/module-web-labs` |
| Base | the `main` sha after S merges (re-create the worktree then; the one created at wave 0 is a placeholder) |
| Merge position | **always last**; holds the docs lease last for reconciliation |
| DoD items | 4-UI, 7 (acceptance test only — Bruno runs the live proof), assembly |

## Owned globs (repo-relative)

- `packages/studyloop/src/studyloop/web/routes/modules.py` (new)
- `packages/studyloop/src/studyloop/web/routes/session/_options.py` (the Labs entry)
- `packages/studyloop/src/studyloop/web/static/{index.html,components.js,style.css}`
- `packages/studyloop/src/studyloop/web/static/js/labs.js` (new)
- `packages/studyloop/src/studyloop/web/app.py` — one-line router inclusion only
- `packages/studyloop/src/studyloop/cli/__init__.py` — registrations of C's and R's groups only
- `packages/studyloop/tests/test_web_modules.py`, `tests/js/module-labs.test.js`,
  `tests/e2e/test_module_labs_journey.py`, `tests/acceptance/test_module_kdrill_live.py`,
  `tests/acceptance/uat/**` (the module rubric)
- final docs/changelog reconciliation (W5) under the docs lease
- `openspec/changes/module-contract-v1/evidence/W/**`

## Forbidden

`content/schemas.py`, all of `modules/` and `session/` internals, `learning/`.

## Tasks (each a gate-G commit unless marked red-only)

- **W1 (red-only):** `test_web_modules.py` via `TestClient`: Labs absent with an empty
  lockfile; present after a fixture install; start payload shape (reuses the existing session
  start inside the one claimed session). `js/module-labs.test.js` for the client logic. Red
  because no routes exist. Evidence kept.
- **W2:** routes + `_options.py` entry + Labs HTML/JS/CSS, hidden when the lockfile is empty;
  W1 green; `just test-js` green. C7 binds: one entry, no counters, nothing from `hint`,
  `solution`, `mentorNotes` or the brief in any response or DOM.
- **W3:** register `module` and `drill` Typer groups; include the router; `--help` for both and
  the API route table verified.
- **W4:** Playwright journey: list → start inside the one claimed session → cancel → reload
  re-attaches with no second session → Tab/Shift-Tab/Escape usable → `module remove` → Labs
  gone; explicit module-level timeout; run under `just e2e` **alone** (machine-wide lock).
- **W5:** docs/changelog reconciliation; `acceptance/test_module_kdrill_live.py` gated
  `STUDYLOOP_ACC=1 STUDYLOOP_LIVE=1` with a **sentinel-cluster assertion** (a pre-existing kind
  cluster must survive); UAT rubric for Persona A (tablet 820×1180 over `--lan`) and Persona B
  (clean machine) under `acceptance/uat/`; `just docs` strict; the acceptance test skips
  cleanly without the env vars.

## Contract gaps to watch for

How "start a drill" composes with the existing session-start route and the single-session
claim (ADR-0009); where the lockfile is read from for the web process; anything that would
need a browser-triggered command execution (that is v1.1 — stop and report).
