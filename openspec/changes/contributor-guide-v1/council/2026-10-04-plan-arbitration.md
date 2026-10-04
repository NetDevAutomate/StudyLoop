# Arbitration — contributor-guide planning council (2026-10-04)

**Coordinator:** Kiro (default). **Seats:** gpt-5.6-sol (1,423 w, on budget), deepseek-3.2
(2,015 w), qwen3-coder-next (2,238 w), glm-5 (2,459 w); budget was 1,500. **Brief:**
`2026-10-04-plan-brief.md`. Every repository claim this arbitration relies on was re-verified
against the tree at `b1369a58` by the coordinator; the seat files are the evidence, this file is
the decision. Outcome: `../design.md` (inventory, facts sheet, writing plan) and `../tasks.md`.

## 1. Seat reliability — what was checked

| Seat | Verified | Falsified | Weight |
| --- | --- | --- | --- |
| gpt-5.6-sol | 300-commit counts at `60bbb504` are docs 107 / test 90 (brief said 106/91); shas `2883588f` `6b6a35bd` `8d31f1ec` `e659f8cf` `019624c3` exist with the subjects quoted; `test_adapter_parity.py:170-178` pins that `agents/grok/` must not exist and Grok reuses Codex; `justfile:214-215` runs `check-release-consistency.py --skip-wheel` and the tag/date check is `--release` only (`scripts/check-release-consistency.py:300-336`); `contributing.md:271-286` holds the PR section and the five questions sit at 278-282; `contributor-code-map.md:8-14` says FastAPI + Alpine + HTMX, not React; the Terraform guide **does** have a Naming Standards page (`/naming/`, fetched) | nothing | full |
| qwen3-coder-next | shas `93f30789` `711459c1` `6b6a35bd` exist with the subjects quoted | harness tiers are **4 core + 2 preview** (`harnesses.py:27-28`: kiro, codex, claude, pi / opencode, grok), not "3 core, 2 preview"; `release-consistency` does **not** check bullet style, section presence or "no dated releases in Unreleased" (no such code in the script); `agents/{kiro,…,grok}.py` — `agents/` holds directories and there is no grok one; declared word count 1,382 is false (2,238) | structure only |
| glm-5 | the `--release` semantics in Q3; the per-kind page structure | all five "real" commits mis-subjected: `fa5d76be` is `test(now): RED — …`, `653e825b` is `feat(plan): …`, `a69867bf` is `test(uat): …`, `96806feb` is `fix(web): session timer…`, `fb63fb6b` is `feat(now): …` — none is what the seat says; `contributing.md:197-201 / 203-210 / 219-226` all fall inside **Testing** (the changelog section starts at 264, issues at 288); `test_mcp_inventory_parity.py` and `test_release_consistency.py` do not exist (`test_mcp_session_parity.py` and `test_release_consistency_script.py` do); "Naming Standards page 404" is false | ideas only, no facts |
| deepseek-3.2 | — | all six "real" worked examples (`docs(contributing): add AI usage section`, `test(e2e): add coverage gate self-test`, …) match **zero** commits in the log; claims F5 "misses `agents/<harness>/`" when F5 lists it; claims a brief URL 404s that the brief never gave; cites `contributing.md:300-310` for the five questions (that is *How we prioritise*) | structure only |

Consequence for the writers: **a naming-standard page built on invented history is the exact
failure this guide exists to prevent.** Only GPT's and Qwen's example sets are admitted
(seven verified shas, §4.3 of `design.md`); every further example a writer adds must be
re-verified with `git log -1 --format='%h %s' <sha>` and the transcript kept as a receipt.

## 2. Decisions

### D1. Page inventory: GPT's 20-page flat inventory, no file moves (adopted; two amendments)

Four seats, four shapes: GPT 20 pages flat `docs/contributor-*.md`, no moves; Qwen 18 flat with a
`contributor-audhd.md`, `contributor-git.md` and `contributor-pr-template.md`; GLM 18 flat;
DeepSeek 18 re-homed under `docs/contribute/`, `docs/developer/`, `docs/proposals/` with
"redirect stubs". Picked GPT because (a) K3 says a move must say what keeps old links valid and
DeepSeek's redirect stubs are not a mechanism mkdocs has (`exclude_docs` allowlist, strict build —
a stub is a second page saying "go elsewhere", the K6 loop); (b) root `CONTRIBUTING.md:9-13`
links `docs/contributing.md#your-first-contribution`, `contributor-code-map.md`,
`contributor-testing.md`, `contributor-modules.md` — those four paths and that anchor are the
seed's public surface and stay; (c) nav grouping is what gives the Terraform shape, and nav is
free. Amendments: Qwen's `contributor-audhd.md` becomes a **section** of
`contributor-documentation.md` (how to write a page *here*, one job); Qwen's `contributor-git.md`
and `contributor-pr-template.md` are rejected as pages — fork/branch/PR lives on the PR page,
the template lives at `.github/PULL_REQUEST_TEMPLATE.md` and is shown there. Page list,
groups and nav are in `design.md` §2. `acceptance-testing.md` keeps its path and moves only its
**nav** position under Contribute → Testing (currently a top-level entry, `mkdocs.yml:117`).

### D2. `contributing.md` becomes the numbered router, anchors preserved (adopted from GPT)

Every existing H2 in `docs/contributing.md` (verified list: Development environment 42, Your
first contribution 77, How the repository is organised 118, Making changes 160, Testing 195,
Continuous integration 235, Documentation standards 249, Changelog process 264, Raising a pull
request 271, Submitting an issue 288, How we prioritise 300, AI usage… 310, Security 345, FAQ
356) **stays as an H2** with a 1-3 sentence answer and a link to the page that now owns the
topic. That is what keeps every `contributing.md#…` link valid without moving a file, and the
drift test pins the anchor list. Its body shrinks; it does not duplicate.

### D3. Writers: four, one worktree each, plus one assembler (GPT 6 / Qwen 3 / GLM 3 / DeepSeek 4)

The seats split on count and none of them raised the hazard that decides it: **pre-commit
stashes unstaged changes at commit time**, so several agents committing in one worktree would
stash and restore each other's half-written pages, and a crash mid-hook loses a page. One
worktree per writer, disjoint files, merged by the assembler, removes the hazard; then the count
is set by coherence and the review queue, not by compute. Four, because the reader journeys
are four: *the welcome path and its exit* (environment → debug → PR → changelog), *add a
thing with a test, part A* (CLI, web, MCP, doctor), *add a thing, part B, and the reference*
(harnesses/agents, content, documentation, conventions, code map), *prove it and the proposals*
(testing, acceptance, issues, AI, modules, module index). GPT's six would fragment the welcome
path across two writers; three leaves one writer with eight pages. Ownership table in
`design.md` §5.

### D4. Naming standard: `type(scope): imperative description`, closed types, open scope (4/4 on the shape)

- Types closed to the six the history uses: `feat fix docs test chore ci` (counts above). A new
  type is a change to the standard, i.e. a `docs(contributing)` PR.
- Scope **open** (GPT, GLM) — the smallest stable subsystem (`web`, `mcp`, `doctor`, `agents`,
  `plan`, `now`, `session`, `openspec`, …); omitted for cross-cutting work; `docs(openspec)` for
  change records and specs, `docs(contributing)` for the guide itself. Qwen's closed list with
  "add only via consensus" is rejected: one maintainer, no consensus body, and the history
  already uses ~15 scopes.
- PR title obeys the same grammar. Today merge commits read `Merge PR #NN (branch): subject`
  (4 of 300) and the subject after the colon carries no type — so this is a **new** rule, as K5
  said; the three real PRs are shown normalised (GPT's forms) as the worked examples.
- Intermediate `test(scope): RED — …` commits are allowed (real: `fa5d76be`), never as PR titles.
- Branches: `feat/ fix/ docs/ test/` + short slug (`contributing.md:176-177`), `lane/` reserved.
- PR description: the **existing five questions** (`contributing.md:278-282`) stay the list;
  AI assistance folds under question 2 and the paths of evidence under 3 (GPT's nine-item list
  rejected — five is the AuDHD-sized number and it is already published).
- Subject length: the writer measures the last 300 subjects and states a limit honestly (many
  current subjects exceed 72 characters; the page must not pretend otherwise).

### D5. Changelog: contributor writes the `[Unreleased]` entry in the PR; the gate is honest

Adopted GPT + GLM: the entry is written in learner terms under Added / Changed / Fixed /
Removed / Security before review; the maintainer dates it at release. The page must say what
`just release-consistency` actually checks in ordinary mode (version metadata and the release
note, `--skip-wheel`) and that the dated-heading-vs-tag check runs only under `--release`
(`check-release-consistency.py:300-336`). Qwen's described checks are not real and must not
appear.

### D6. Module index page: GPT's 10 bullets + two from GLM, 12 total; the Click drift test is its guard

Adopted bullets in `design.md` §2 (Proposals). GLM contributes "do not add a `modules:` section
to your config expecting it to work" and "the first useful slice is done when a new contributor
can run one drill, consent to one check, and cancel safely". Forcing function nobody named:
`test_docs_drift.py::test_studyloop_example_resolves` resolves every fenced `studyloop …` line
on a listed page against the real Click tree, so once the page is listed, a **proposed**
`studyloop module add` shown as a fenced example **fails the suite**. Proposed commands are
therefore written in prose and labelled proposed, never fenced. Must-not-promise list in §2.

### D7. Truthfulness: one parameterised sibling test, receipts as a review gate (GPT's C/H/L/M; Qwen's per-page files rejected)

`test_contributor_guide_drift.py`, parameterised over the inventory — not fourteen files (Qwen).
Patterns: **C** command manifest (fenced `just` recipes resolve against `justfile`; `uv run
pytest <path>` paths collect; cited paths exist; a bounded allowlist of read-only commands is
*executed* with a sanitised `HOME` and exit 0 asserted — never `just e2e`, never anything that
starts a session); **H** structure (answer paragraph or numbered list before the first H2; ≥ 1
numbered list; line cap); **L** every local link and `#anchor` resolves, the router's anchor list
is pinned; **M** module-index invariants ("design stage" in paragraph 1, the §9 link, no
present-tense registry/install claim, no fenced proposed command); **F** the three cross-page
facts read from source constants (`harnesses.py`, `pyproject.toml` addopts, the branch-prefix set)
so a page that contradicts the code fails. Existing `_STUDYLOOP_EXAMPLE_DOCS` is extended with
every new page. Writers prove "I ran it" with a committed receipt per page
(`evidence/<writer>/commands.txt`: `$ command`, exit code, first lines, sha, UTC time); the
assembler rejects a page whose fenced commands are not all in its receipt.

### D8. Scaffold first, so writers work red-to-green

Not proposed by any seat; follows from D3 + D7. Before any writer starts, the assembler commits
on the integration branch: 15 stub pages carrying a marker the drift test rejects, their
allowlist + nav lines, and `test_contributor_guide_drift.py` **red** on every stub. Writers
branch from that commit, so each can run `just docs` strict and the drift test on its own pages
while writing, and the assembler's merge is file-disjoint by construction.

### D9. Harness tiering is a cross-page fact, stated once per page from the constants

`CORE_HARNESSES = (kiro, codex, claude, pi)`, `PREVIEW_HARNESSES = (opencode, grok)`
(`harnesses.py:27-28`); Grok reuses Codex's definition (`test_adapter_parity.py:170-178`);
additions declined (`contributing.md:170-175`). Qwen's "3 core" would have shipped a wrong count.

### D10. Terraform mapping

Pages mirror the reference where a real analogue exists (fetched nav: Welcome, Development
Environment, Contribution Guides, Acceptance/Unit Tests, Continuous Integration, Changelog
Process, Raising a Pull Request, How We Prioritize, AI Usage, Developer Reference incl. Naming
Standards and Debugging, Submit an Issue, FAQ). Code-level naming (files, tests, scopes) goes to
`contributor-conventions.md` (the Naming Standards analogue); branch/commit/PR naming goes on the
PR page, because that is where the reader is when they need it (K6: no "see elsewhere").

## 3. Rejected, with reasons

- DeepSeek's `docs/contribute/` re-homing — breaks the seed's four public paths for no reader
  benefit; nav gives the grouping.
- Qwen's closed scope list, per-page drift-test files, `contributor-git.md`,
  `contributor-pr-template.md`, `contributor-audhd.md` as a page.
- GLM's "new CI check validates PR title against a regex" — out of this change's DoD; recorded as
  a follow-up in `tasks.md` §5.
- GPT's nine-item PR description — the five published questions stay.
- "Acceptance never runs in CI" needs one qualifier: `nightly-uat.yml` runs `-m integration`
  nightly (verified), **not** acceptance; so acceptance/UAT are opt-in only, integration runs
  nightly. Pages say exactly that.

## 4. Corrections to the brief (seat 9s, verified)

F2 counts are 107/90 (GPT). F5's `agents/<harness>/` is five directories, not six — Grok has none
by design (GPT). F6 overstated ordinary `release-consistency` (GPT). F9's `session-query search`
anecdote is from the owner's memory, not the current drift test, which documents R-31/R-61
(GPT; kept as owner-reported, labelled). The brief's "six supported harnesses" is right; the
guide must add the core/preview tiering (Qwen's point, with the corrected numbers).

## 5. Catch-rate row

| Review | Seats | Raised | Verified and acted | Discounted (why) |
| --- | --- | --- | --- | --- |
| guide plan | gpt-5.6-sol, deepseek-3.2, qwen3-coder-next, glm-5 | ~45 | GPT: inventory, router-with-anchors, C/H/L/M tests, receipts, four brief corrections, seven real shas; Qwen: harness tiering (count corrected), two real shas; GLM: two module-index bullets, `--release` semantics | GLM: all five example subjects fabricated, three line cites wrong, two test files invented, false 404; DeepSeek: six fabricated examples, F5 misread, invented URL; Qwen: 3+2 tiers, invented release checks, false word count |
