# Council brief — implementation & testing plan for "StudyLoop Modules — contract v1"

Date: 2026-10-04. Coordinator: Kiro (Claude lineage). This is the **planning** pass of the
multi-model deliberation: four model families answer this one brief in parallel; the
coordinator arbitrates into the change's `design.md` and `tasks.md`. A later **review** pass
with the same families checks the implementation against its own claims.

## What you are planning

An implementation and testing plan for the amended proposal at
`openspec/changes/module-contract-v1/proposal.md` (repository commit `54d79e88`; read it in
full, especially §5.5, §5.7, §6, §7 and the seven-item definition of done in §9). The plan
covers the MVP (DoD items 1–7) and names v1.1 (browser **Check progress**) as a follow-on. It
must be executable by several AI agents working **in parallel git worktrees**, each on its own
`feat/…` branch with disjoint file ownership, merging in a defined order, with a
**council-of-models review at the milestones where a wrong decision is expensive**, and it
must include **representative user testing through the Web UI with Playwright**.

## Who the deliverable is for, and what "ready" means

The owner is a solo maintainer with roughly two hours a day of review bandwidth, orchestrating
up to four concurrent agents. "Ready" means: every lane has a branch name, an owned file set,
a commit sequence whose every commit passes the gates, a test plan with countable acceptance,
and a merge position; the shared-file hotspots are assigned to exactly one lane or serialised;
the council milestones are named with what each reviews; and the whole thing has a critical
path in calendar days that the owner can believe.

## Hard constraints — settled, NOT up for review

Flag a violation; do not re-argue.

- C1. The amended proposal is the spec. Its contract decisions (§5.3 identity fields, §5.5
  execution model, §5.7 transient-only recording + mentor delivery, MC001–MC016, local-path
  `module add`, browser checks in v1.1, view-only credential in v2) are closed.
- C2. Branch names are `feat/…`, `fix/…`, `docs/…` or `test/…`. **Never `lane/…`**
  (`docs/contributing.md:175`): the existing `lane/m<n>-` guard in
  `packages/studyloop/tests/_lane_ownership.py` belongs to a finished remediation.
- C3. Every commit passes the gates: pre-commit (including the `pre-push` stage, which runs
  pyright) and `just preflight` = `lint typecheck test test-js docs release-consistency
  spec-check` (`Justfile`). Docs and `CHANGELOG.md` land in the same change as the code.
- C4. Default tests are offline: `addopts` deselects `integration`, `e2e`, `live_*`,
  `acceptance`, `uat` (`pyproject.toml`); e2e modules carry their own explicit timeouts;
  no Docker, kind, model or network in the default lane.
- C5. Agents have full local git control (branches, worktrees, commits). Pushes to `main` are
  the owner's. Destructive git (`reset --hard`, `branch -D`, force-push) is never automatic.
- C6. `uv` only (`uv run …`, `just sync-dev` in a fresh worktree); never pip/poetry.
- C7. The AuDHD and Socratic rules of the review brief (`2026-10-04-review-brief.md` C1–C2)
  bind every UI decision: one Labs entry, hidden when no module is installed, no overdue
  counters, no answer-giving outside the mentor.
- C8. Nothing registry-shaped is built. A parallel OpenSpec change `module-registry-v1` exists
  in the tree (untracked, written by another session); it is **parked**, not part of this plan.

## Verified repository facts planners must build on (cite more if you find them)

- F1. A **fresh worktree has no venv**: run `just sync-dev` (or `sync-web`) first and prefix
  `just`/`uv run` with `env -u VIRTUAL_ENV` (`docs/contributing.md:61,74`).
- F2. **Playwright e2e harness exists**: `packages/studyloop/tests/e2e/_env.py` builds a temp
  study vault + a subprocess-hosted server + failure artifacts (screenshot, HTML, console);
  `playwright/serve_hermetic.py` runs the same hermetic world for interactive driving;
  `tests/e2e/surface.py`, `coverage_collector.py` exist. Journeys to mirror:
  `test_representative_user_journey.py`, `test_journey_new_user_first_plan.py`,
  `test_body_double_journey.py`. A separate `packages/studyloop/tests/journeys/` is run by
  `just journeys`.
- F3. **Acceptance and UAT tiers already exist**: markers `acceptance` (opt in with
  `STUDYLOOP_ACC=1`, `just testacc`) and `uat` (`STUDYLOOP_UAT=1`, `just testuat`), described
  in `docs/acceptance-testing.md`. Representative user testing must reuse these tiers, not
  invent a fourth.
- F4. **A lane-ownership guard exists** (`tests/_lane_ownership.py`, `tests/test_lane_ownership.py`,
  `tests/fixtures/lane_ownership.yaml`): fnmatch patterns per lane, `shared` always allowed,
  files owned only by other lanes are violations, unmapped files logged. It keys lanes off
  `lane/m<n>-` branch names, which C2 forbids — decide whether to re-key it or replace it.
- F5. Unit suite: ~4,800 test functions across ~330 files, ~83 s; `test_docs_drift.py` exists
  and checks docs against code.
- F6. Web UI is Alpine.js/HTMX with **no build step**; non-vendor JS ≈ 8,600 lines under
  `packages/studyloop/src/studyloop/web/static/`; `test-js` runs JS tests.
- F7. Shared-file **hotspots** that several lanes will want: `content/schemas.py`, the CLI
  command registration (`cli/__init__.py` / the Typer app), `web/routes/session/_options.py`,
  `web/static/index.html` + `components.js` + `style.css`, `mkdocs.yml`, `CHANGELOG.md`,
  `docs/`. Another session is **actively editing** `docs/contributing.md`, `CONTRIBUTING.md`,
  `CHANGELOG.md`, `mkdocs.yml` and `agents/kiro/*.json` in the main checkout right now.
- F8. The seam facts from the review: `learning/practice.py:282-290` runs `shell=True` in the
  inherited environment; `:179-188` records a `confident`/`struggling` observation; only
  `cli/_practice.py` calls verification; `web/ws_origin.py` is consumed only by WebSocket
  routes; `PracticeTask`/`PracticeVerification` are `extra: forbid`
  (`content/schemas.py:270-305`).
- F9. Nobody has yet read how a message can be injected into the live mentor's PTY/ACP
  session from the server (`web/routes/session/_transport.py`, `session/transport.py`).
  DoD item 5 depends on this; the plan must put a **design-first spike** before any
  implementation of it.
- F10. `kiro-cli chat --list-models` offers OpenAI, DeepSeek, Zhipu, Alibaba and MiniMax
  families beside Claude; `spawn_run` takes one `model` per call; at most four agents run
  concurrently on this host.

## Known risks (numbered, so answers can reference them)

- R1. Mentor-delivery transport unverified (F9) — a late discovery here re-sequences the UI lane.
- R2. Runner security — argv/env/digest/consent is the one place a plausible-looking
  implementation can be quietly wrong; needs an adversarial review before merge.
- R3. Hotspot collisions (F7) between parallel lanes, and with the other session's in-flight
  docs work.
- R4. Agent-written tests that pass trivially: the MC001–MC016 fixture set must be proven to
  FAIL on each violation, and the "no observation written" test must be proven to fail
  against the current `practice verify` path.
- R5. Playwright flakiness and timeouts (C4; the e2e modules' own deadlines).
- R6. The live kind lane can only run on the owner's machine (Docker); Bruno's conversion is
  not under the plan's control.
- R7. Scope creep from the parked registry change (C8).
- R8. Estimate uncertainty: the proposal says 40–50 agent-hours for the MVP after council
  correction; the council itself ranged 42–85 for the earlier scope.

## Out of scope — do not plan work here

v2 grants and the view-only credential; anything registry/index; Web UI installation; browser
drill authoring; the second (SQL) module's implementation; Bruno's kdrill conversion internals
(the plan only names its interface and its proof); CI hosting changes.

## Questions — answer every one, countably, in this order

- Q1. **Lanes.** Propose the lanes (3–6). For each: name, `feat/…` branch, worktree, owned
  paths as fnmatch globs, explicitly forbidden paths, the DoD items it delivers. Ownership must
  be disjoint; name which single lane owns each F7 hotspot (or how it is serialised), and how
  the plan avoids the other session's in-flight `docs/`/`CHANGELOG.md`/`mkdocs.yml` edits.
- Q2. **Merge DAG and strategic commits.** The dependency order between lanes, and per lane a
  commit sequence of at most six bisectable commits, each with the gate it must pass and the
  evidence it leaves (test name, fixture, doc).
- Q3. **Test plan per DoD item 1–7.** For each: unit / CLI (`CliRunner`) / API (`TestClient`) /
  JS / e2e / acceptance-UAT / live, with concrete test module names, the countable acceptance,
  and how R4 is defeated (which test is shown failing first, against what).
- Q4. **Representative user testing.** Define 2–3 personas (at minimum: an AuDHD learner on a
  tablet over `--lan`; a new contributor following the docs from a clean machine). For each, a
  Playwright journey with numbered steps and assertions covering: Labs hidden with no module,
  install via CLI, Labs visible, start a drill inside the one session, cancel, reload, keyboard
  and focus, missing prerequisites, module removed. State the marker/tier (F3), the runtime
  budget, and the artifacts captured. Say what "pass" means for a human sign-off.
- Q5. **Fan-out and council schedule.** How many agents run at once and in what roles
  (implementer per lane, test author, reviewer); what each agent's brief must contain; which
  milestones get a council-of-models review (name them, say what each council reviews and what
  it must NOT be used for), and what evidence is handed to the council each time.
- Q6. **Risks.** The top five of R1–R8 (or new ones) with mitigation and a detection test or
  gate for each.
- Q7. **Effort and critical path.** Agent-hours per lane; critical path in calendar days with
  four concurrent agents and two owner-hours a day; the single item you would cut if the owner
  wants the MVP a week sooner.
- Q8. **Where will the other planners be wrong?** Name the structure you expect another
  model to propose that you reject, and why.
- Q9. **What does this brief get wrong?** Contradictions, missing facts, anything you checked
  that disagrees with F1–F10 (cite the file).

## Rules for the plan

- Verify before planning: read the proposal and the files cited in F1–F9 with **absolute
  paths rooted at `/Users/ataylor/code/personal/tools/studyloop`** — never a relative path
  (a reviewer in the previous round reported a directory empty because it listed the wrong
  cwd). Cite `path:line` for every code fact.
- Do **not** modify any existing file, do **not** run writing git commands, do not create
  worktrees or branches, do not run the test suite. Read-only, plus your own result file.
- Another model family is planning from this same brief; a coordinator arbitrates. Do not hedge
  toward consensus. Divergence is wanted on Q1 (lane shape), Q5 (council schedule) and Q7.
- Budget: 1,400–1,800 words. Headings `Q1` … `Q9` exactly; tables welcome; end with one line
  `Critical path: <N> calendar days` and one line `Plan verdict: build as proposed | re-sequence
  first | cut scope first` with a sentence of rationale.
