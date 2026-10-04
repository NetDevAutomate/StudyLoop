# Design — the StudyLoop contributor guide (contributor-guide-v1)

**Status:** arbitrated plan, 2026-10-04 — not started. Decisions and their reasons:
`council/2026-10-04-plan-arbitration.md` (four planning seats; GPT-5.6's inventory adopted with
two amendments; GLM and DeepSeek discounted on facts, see §1 there). What is being built is
`proposal.md`; this document says *which pages*, *by whom*, *in what order* and *how each page
is kept true*. Paths are repo-root-relative under `/Users/ataylor/code/personal/tools/studyloop`.
Every fact in §3 was verified by the coordinator against the tree at `b1369a58`; writers cite
§3, and anything not in §3 they verify themselves and receipt (§6).

## 1. Shape in one paragraph

Twenty flat pages under `docs/`, grouped by **nav** into the Terraform guide's shape (Welcome ·
Contribute ·  Testing · Process · Developer Reference · Proposals). No file moves: the seed's four
pages keep their paths and `docs/contributing.md` becomes the numbered *router* whose every
existing H2 survives as an anchor. One **scaffold commit** lands first — stub pages, allowlist
and nav lines, and a parameterised drift test that is red on every stub — then **four writers**
in four worktrees take disjoint page sets red-to-green, running every command they document and
committing a receipt per page. One **assembler** (the coordinator) merges, reconciles
cross-links and the changelog, and runs the gates; a **four-seat council** reads the finished
guide; the owner reads it; one outside reader walks *Welcome* on a clean machine. The docs
lease (`docs/`, `mkdocs.yml`, `CHANGELOG.md`) is held by this change from the scaffold commit
until the merge to `main`; module-contract tasks S3 and W5 queue behind it.

## 2. Page inventory (20 pages) and nav

State: **extend** = exists, rewritten in place, anchors kept; **exists** = light touch
(cross-links, nav position); **new** = created by the scaffold as a stub. "Mirror" is the
Terraform page the page borrows its *shape* from (nav fetched 2026-10-04). "Examples" are
candidates the writer must run and may replace; "Pin" names the drift-test pattern (§6).

### Welcome (nav: Contribute → Start here)

| # | Page | One job | Mirror | State | Example candidates | Pin |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `docs/contributing.md` | Numbered clone → merged-PR path; one paragraph per step linking the owning page; keeps every current H2 as an anchor (§3 F10) | Welcome (index) | extend | `just preflight` | C H L + anchor list |
| 2 | `docs/contributor-environment.md` | Install and verify the tools: uv, just, tmux, Node, Playwright; sync the workspace venv; prove the import | Development Environment | new | `just sync-dev`, `uv run studyloop --version`, `uv run studyloop doctor` | C H L |
| 3 | `docs/contributor-debugging.md` | Reproduce → isolate → read the error → check assumptions → trace; where logs and session state live; the sandbox/TMPDIR gotcha | Debugging | new | `uv run studyloop doctor`, `uv run --group dev pytest <one test> -x -vv` | C H L |

### Contribute — per kind of change (nav: Contribute → Make a change)

| # | Page | One job | Mirror | State | Example candidates | Pin |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | `docs/contributor-cli.md` | Add or change a Click command (`cli/_*.py`, `@click.command`, mounted lazily by `LazyGroup` in `cli/__init__.py` — the CLI is Click, not Typer) with its `CliRunner` test and `--help` text | Add a New Resource Type | new | `uv run studyloop --help`, `uv run --group dev pytest packages/studyloop/tests/test_cli_*.py -q` | C H L |
| 5 | `docs/contributor-web.md` | Add or change a FastAPI route + Alpine/HTMX UI (`web/routes/`, `web/static/`), TestClient test, one Playwright journey | Add a New Resource Type | new | `just test-web`, `just test-js` | C H L |
| 6 | `docs/contributor-mcp.md` | Add or change an MCP tool (`mcp/`), parity with the CLI, its test | Add a New Data Source Type | new | `uv run --group dev pytest packages/studyloop/tests/test_mcp_*.py -q` | C H L |
| 7 | `docs/contributor-doctor.md` | Add a diagnostic (`doctor/`): `CheckResult` shape, honest wording, no side effects | Bugs and Enhancements | new | `uv run studyloop doctor` | C H L |
| 8 | `docs/contributor-harnesses-agents.md` | Change an adapter or an agent prompt/skill; the six harnesses, 4 core + 2 preview; Grok reuses Codex; additions are declined and why | Add a New AWS Service | new | `uv run --group dev pytest packages/studyloop/tests/test_adapter_parity.py -q` | C H L F |
| 9 | `docs/contributor-content.md` | Change content schemas and the generation pipeline (`content/`), `extra: forbid`, generator tests | Add a New Resource Type | new | `just test-content` | C H L |
| 10 | `docs/contributor-documentation.md` | Write a truthful site page: allowlist + nav, strict build, drift tests, **and the AuDHD writing rules** (one job, answer first, numbered steps, line cap) | Documentation Changes | new | `just docs` | C H L |

### Testing (nav: Contribute → Prove it)

| # | Page | One job | Mirror | State | Example candidates | Pin |
| --- | --- | --- | --- | --- | --- | --- |
| 11 | `docs/contributor-testing.md` | Choose the tier (default / integration / e2e / acceptance / UAT), write the focused test, the patterns the cookbook already shows | Unit Tests | extend | `uv run --group dev pytest packages/studyloop/tests/test_contributor_examples.py -q` | C H L F |
| 12 | `docs/acceptance-testing.md` | Opt-in acceptance and UAT with a real harness | Acceptance Tests | exists (nav moves here) | `just testacc kiro` (not executed by the test; resolved) | C L |

### Process (nav: Contribute → Land it)

| # | Page | One job | Mirror | State | Example candidates | Pin |
| --- | --- | --- | --- | --- | --- | --- |
| 13 | `docs/contributor-changelog.md` | Write the `[Unreleased]` entry in the PR, which section, what `release-consistency` really checks | Changelog Process | new | `just release-consistency` | C H L |
| 14 | `docs/contributor-pull-requests.md` | Branch, commit-subject and PR-title standard (§4) with eight real examples; the five-question description; the PR template; what reviewers check | Raising a Pull Request | new | `git log -1 --format='%h %s' e659f8cf` | C H L F |
| 15 | `docs/contributor-issues-prioritisation.md` | Report a bug or propose a change (what to attach, `doctor` output redacted); the priority order maintainers use | Submit an Issue · How We Prioritize | new | `uv run studyloop doctor` | C H L |
| 16 | `docs/contributor-ai.md` | Disclose AI assistance, own the result, the LiteLLM-gateway option | AI Usage | new | `git log -1 --format=%B` | C H L |

### Developer Reference (nav: Developer Reference)

| # | Page | One job | Mirror | State | Example candidates | Pin |
| --- | --- | --- | --- | --- | --- | --- |
| 17 | `docs/contributor-code-map.md` | Which layer owns what; request flow; where a change of each kind lands | none | extend | `rg -n 'def load_practice_deck' packages` | C H L |
| 18 | `docs/contributor-conventions.md` | Code-level naming (modules, tests, fixtures, scopes), OpenSpec changes and `spec-check`, ADRs and their index | Naming Standards | new | `just spec-check` | C H L |

### Proposals (nav: Proposals — design stage)

| # | Page | One job | Mirror | State | Example candidates | Pin |
| --- | --- | --- | --- | --- | --- | --- |
| 19 | `docs/contributor-modules.md` | The proposed module contract, as a proposal | none | extend | none fenced; links to `openspec/changes/module-contract-v1/proposal.md` | H L M |
| 20 | `docs/contributor-module-index.md` | The proposed module index — "design stage" in paragraph 1; what exists, what does not, what not to do today | none | new | none fenced (D6: a fenced proposed `studyloop module …` line fails `test_studyloop_example_resolves`) | H L M |

**Module-index outline (12 bullets, binding):** 1 design stage, nothing built — first paragraph;
2 link `openspec/changes/module-contract-v1/proposal.md` §9 and the contract proposal; 3 goal:
topic-specific practice without topic-specific core dependencies; 4 what exists today (JSON
practice decks, `verification.kind: command`, per-command consent, `setupCommand` is metadata);
5 what does not (installer, index, automatic execution, trust model, stable manifest); 6 the
staged path: contract → first module → second topic proves the boundary → index → lifecycle;
7 proposed vocabulary (manifest, capabilities, prerequisites, scaffolding levels) labelled
*proposed*; 8 safety invariants proposed (modules declare, core executes; learner sees prompt
and criteria only); 9 what a would-be author can do today: open an issue, convert content to a
`PracticeDeck`, read #53; 10 "do not add a `modules:` section to your config expecting it to
work"; 11 the first slice is done when a new contributor can run one drill, consent to one
check and cancel safely; 12 open questions and where they are decided. **Must not promise:**
discovery, installation, safety certification, compatibility, acceptance of third-party code,
a timeline.

**Nav** (replaces `mkdocs.yml:112-117`; `acceptance-testing.md` leaves the top level):

```yaml
  - Contribute:
    - Start here:
      - Start Contributing: contributing.md
      - Development Environment: contributor-environment.md
      - Debugging: contributor-debugging.md
    - Make a change:
      - A CLI Command: contributor-cli.md
      - A Web Route and UI: contributor-web.md
      - An MCP Tool: contributor-mcp.md
      - A Doctor Check: contributor-doctor.md
      - Harnesses and Agents: contributor-harnesses-agents.md
      - Content Schemas and Pipeline: contributor-content.md
      - Documentation: contributor-documentation.md
    - Prove it:
      - Testing Cookbook: contributor-testing.md
      - Acceptance Testing: acceptance-testing.md
    - Land it:
      - Changelog Process: contributor-changelog.md
      - Raising a Pull Request: contributor-pull-requests.md
      - Issues and Prioritisation: contributor-issues-prioritisation.md
      - AI Usage: contributor-ai.md
  - Developer Reference:
    - Code Map: contributor-code-map.md
    - Conventions: contributor-conventions.md
  - Proposals (design stage):
    - Optional Modules (Proposal): contributor-modules.md
    - Module Index (Proposal): contributor-module-index.md
```

Non-page artefacts: `.github/PULL_REQUEST_TEMPLATE.md` (new; the five questions);
`packages/studyloop/tests/test_contributor_guide_drift.py` (new); `mkdocs.yml` (15 allowlist
lines + nav); `CHANGELOG.md` (`[Unreleased]` → `### Added`, one entry);
`openspec/changes/contributor-guide-v1/evidence/<writer>/commands.txt` receipts.

## 3. Verified facts sheet — writers cite these; anything else they verify and receipt

- F1 Branch prefixes `feat/ fix/ docs/ test/`; `lane/` reserved — `docs/contributing.md:176-177`.
  Maintainers merge with a merge commit (same lines).
- F2 Harness additions declined; a proposal must define seven things — `docs/contributing.md:170-175`.
- F3 The five PR questions — `docs/contributing.md:278-282` (section *Raising a pull request*
  starts at 271).
- F4 Harness tiers — `packages/studyloop/src/studyloop/harnesses.py:27-30`:
  `CORE_HARNESSES = ("kiro", "codex", "claude", "pi")`, `PREVIEW_HARNESSES = ("opencode", "grok")`,
  `RELEASE_HARNESSES` = both. Six in total.
- F5 `agents/` holds `claude codex kiro opencode pi shared skills mcp manifest.json`; **no
  `agents/grok/`** — Grok projects the Codex definition and
  `test_adapter_parity.py::test_grok_projects_the_codex_definition` (lines 170-178) fails if
  `agents/grok/` appears.
- F6 `just release-consistency` = `uv run python scripts/check-release-consistency.py --skip-wheel`
  (`justfile:214-215`); `release-consistency-shipped` adds `--release --pre-tag`
  (`justfile:231-232`); the tag-exists and CHANGELOG-date-on-or-after-tag check is `--release`
  only (`scripts/check-release-consistency.py:300-336`).
- F7 Default test selection: `pyproject.toml:98` `addopts` deselects `integration e2e live_kiro
  live_provider live_obsidian live_xtiles acceptance uat`. `just preflight` = `lint typecheck test
  test-js docs release-consistency spec-check` (`justfile:279`). `just e2e` takes a machine-wide
  lock at `/tmp/studyloop-e2e.lock` (`justfile`, recipe `e2e`); one run per machine.
- F8 Tier table — `docs/acceptance-testing.md:12-20`: acceptance is `STUDYLOOP_ACC=1`, "opt-in,
  never runs in CI"; UAT adds `STUDYLOOP_UAT=1`. `.github/workflows/nightly-uat.yml` runs
  `pytest -m "integration and not live_provider and not live_kiro"` nightly at 03:00 UTC — so
  *integration* runs nightly in CI; acceptance and UAT never do.
- F9 `mkdocs.yml:59-88` is the `exclude_docs` allowlist (`**` then `!/page.md`); the Contribute nav
  is `mkdocs.yml:112-117`. ADRs, plans and agent instructions stay out of the site by design.
- F10 `docs/contributing.md` H2s and lines: Contents 26 · Development environment 42 · Your first
  contribution 77 · How the repository is organised 118 · Making changes 160 · Testing 195 ·
  Continuous integration 235 · Documentation standards 249 · Changelog process 264 · Raising a
  pull request 271 · Submitting an issue 288 · How we prioritise 300 · AI usage, and models
  through a LiteLLM gateway 310 · Security 345 · FAQ 356. Root `CONTRIBUTING.md:9-13` links
  `docs/contributing.md#your-first-contribution`, `contributor-code-map.md`,
  `contributor-testing.md`, `contributor-modules.md`.
- F11 Existing drift tests — `packages/studyloop/tests/test_docs_drift.py`, 8 tests:
  `test_studyloop_example_resolves` (307; every fenced `studyloop …` line on the pages listed in
  `_STUDYLOOP_EXAMPLE_DOCS` resolves against the real Click tree), `test_session_query_since_examples`
  (341), `test_yaml_block_keys_are_known` (524) and five pinned-claim tests. **No subprocess.**
  `test_contributor_docs.py` has 3 tests (page published and linked; cookbook links to real
  collected examples; module guide preserves proposal/execution boundaries).
- F12 UI stack: FastAPI with Alpine, HTMX and browser JavaScript under `web/static/`; **not
  React** — `docs/contributor-code-map.md:9-12`.
- F13 Commit subjects, last 300 at `60bbb504`: `docs` 107 · `test` 90 · `fix` 49 · `feat` 37 ·
  `chore` 6 · `ci` 1 · merge commits 4 (`Merge PR #NN (branch): subject`).
- F14 Verified example commits (sha → subject, `git log -1 --format='%h %s'`):
  `e659f8cf fix(web): give the voice health probe a budget a healthy host fits in` ·
  `019624c3 fix(mcp): record_teachback refuses blank concept/topic and names its failure honestly` ·
  `93f30789 fix(web): revalidate CSS and JS before reuse, like the page itself` ·
  `711459c1 feat(kiro): web ACP sessions run StudyLoop's own \`studyloop\` agent` ·
  `fa5d76be test(now): RED — a plan-related active primary carries a warm-up first move on its own material (rubric 3c (e1))` ·
  `2883588f Merge PR #40 (fix/ws-drained-pull-future): read a done pull future on every WS pump exit` ·
  `6b6a35bd Merge PR #41 (feat/learning-tier-fed): item 1, the mentor writes (S1-0 through council review 9)` ·
  `8d31f1ec Merge PR #42 (fix/coverage-gate-selftest-timeout): coverage-gate self-test carries its own timeout`.
- F15 Terraform guide nav (fetched 2026-10-04): Welcome · Contribute (Development Environment;
  Contribution Guides: Add a New AWS Service / Resource Type / Data Source Type / … / Bugs and
  Enhancements / Documentation Changes; Acceptance Tests; Unit Tests; Continuous Integration;
  Changelog Process; Raising a Pull Request; How We Prioritize; AI Usage) · Developer Reference
  (incl. Debugging, Naming Standards, Makefile Cheat Sheet, Design Decision Log) · Submit an
  Issue · FAQ. The Naming Standards page exists at `/naming/`.
- F16 Sandbox facts for agents (from `openspec/changes/module-contract-v1/briefs/00-common.md`):
  `export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"` before any test; `env -u VIRTUAL_ENV` before
  `just`/`uv`; fresh worktree needs `just sync-dev` and an import-path proof.

## 4. The naming standard (what page 14 states)

### 4.1 Grammar

```
<type>(<scope>): <imperative description>        # commit subject AND pull-request title
<type>: <imperative description>                 # cross-cutting: scope omitted
```

- **type** — closed set, the six the history uses: `feat` `fix` `docs` `test` `chore` `ci`
  (F13). Adding a type is a change to this page.
- **scope** — open; the smallest stable subsystem the change lands in (`web`, `mcp`, `doctor`,
  `agents`, `plan`, `now`, `session`, `openspec`, …). `docs(openspec)` for change records and
  specs; `docs(contributing)` for this guide. Omit when the change is genuinely cross-cutting.
- **description** — imperative, says the *outcome* ("give the voice probe a budget"), no trailing
  period. The writer measures subject length over the last 300 commits and states the limit that
  the history actually keeps; the page must not claim a 72-character rule the repo breaks.
- Intermediate red-first commits may read `test(scope): RED — …` (F14 `fa5d76be`); a PR title may not.
- **Branch**: `<type>/<short-slug>` with type ∈ `feat fix docs test` (F1); `lane/…` reserved.
- **PR title** uses the commit grammar. It is new: today's four merge commits carry the subject
  without a type (F13), so the page shows the three real PRs **normalised**:
  `#40 → fix(web): read a done pull future on every WS pump exit`,
  `#41 → feat(learning-tier): the mentor writes learning events`,
  `#42 → fix(gate): give the coverage self-test its own timeout`.
- **PR description**: the five questions (F3), unchanged; AI assistance is answered under 2,
  evidence paths under 3, and `.github/PULL_REQUEST_TEMPLATE.md` carries exactly those five.
- **PR → changelog**: one learner-facing bullet under `[Unreleased]` per user-visible change
  (`feat`→Added, `fix`→Fixed, behaviour change→Changed, removal→Removed, security→Security);
  `test`, `docs`, `chore`, `ci` normally none, and the PR says so under question 2.

### 4.2 Worked examples — eight, all from F14, each shown as sha · subject · what makes it right

Five ordinary subjects (`e659f8cf`, `019624c3`, `93f30789`, `711459c1`, `fa5d76be`) and the three
PRs normalised. A writer who wants another example runs `git log -1 --format='%h %s' <sha>`,
pastes the output into the receipt, and only then into the page.

## 5. Writers, worktrees, ownership, order

| Agent | Branch · worktree | Owns (writes) | Pages |
| --- | --- | --- | --- |
| **A0 scaffold** (assembler, first) | `feat/contributor-guide` · `../studyloop-wt/contributor-guide` | 15 stub pages (every *new* page, each containing the marker `<!-- GUIDE-STUB -->` and a one-line purpose), `mkdocs.yml` allowlist + nav, `packages/studyloop/tests/test_contributor_guide_drift.py` **red on every stub**, extension of `_STUDYLOOP_EXAMPLE_DOCS` in `test_docs_drift.py`, `evidence/A0/red.txt` | — |
| **W-A welcome & exit** | `feat/contributor-guide-a` · `../studyloop-wt/contributor-guide-a` | pages 1, 2, 3, 13, 14 + `.github/PULL_REQUEST_TEMPLATE.md` | 5 |
| **W-B make a change, part A** | `feat/contributor-guide-b` · `…-b` | pages 4, 5, 6, 7 | 4 |
| **W-C make a change, part B + reference** | `feat/contributor-guide-c` · `…-c` | pages 8, 9, 10, 17, 18 | 5 |
| **W-D prove it + proposals** | `feat/contributor-guide-d` · `…-d` | pages 11, 12 (cross-links only), 15, 16, 19, 20 | 6 (two light) |
| **A1 assembly** (coordinator) | `feat/contributor-guide` | merges a–d (file-disjoint), cross-link pass, `CHANGELOG.md` entry, full drift test, `just preflight`, `just docs` strict | — |

Rules: a writer touches only its pages and `evidence/<writer>/`; **nobody but A0/A1 touches
`mkdocs.yml`, `test_docs_drift.py`, `test_contributor_guide_drift.py` or `CHANGELOG.md`**; a
writer who needs a cross-link to a sibling's page links the path from §2 (the stub exists, so
`just docs` strict passes) and never edits the sibling. Writers branch from the **scaffold sha**,
not from `main`. Each page is one commit (`docs(contributing): <page> — <one line>`) plus its
receipt in the same commit; pre-commit runs at commit time; `env -u VIRTUAL_ENV just docs` and
`pytest packages/studyloop/tests/test_contributor_guide_drift.py -k <page>` green before the
commit. Writers run no `just e2e`. Why four worktrees and not one: pre-commit stashes unstaged
changes while hooks run, so parallel agents committing in one tree stash and restore each other's
half-written pages, and a crash mid-hook loses a page (arbitration D3).

Order: A0 → (W-A ∥ W-B ∥ W-C ∥ W-D) → A1 → council review (§8) → fixes by the coordinator →
owner read → merge to local `main` → lease released (S3, W5 unblocked) → owner pushes → DoD 7
outside reader.

**Three cross-page facts the assembler checks by test (F pattern):** harness names and tiers
(F4, F5); tier names, markers and what runs where (F7, F8); branch prefixes and the type set
(F1, F13). Each is read from source in the test and every page mentioning it is asserted
against the same value.

## 6. Truthfulness — `test_contributor_guide_drift.py`

One file, parameterised over the §2 inventory (a module-level tuple of `(page, group,
line_cap)`), default-tier, no network:

- **C — commands.** Every fenced `bash`/`sh`/`console` line beginning `just <recipe>` resolves to
  a recipe in `justfile`; every `uv run --group dev pytest <path>` path exists; every
  `studyloop …` line is resolved by the existing Click-tree test (page listed in
  `_STUDYLOOP_EXAMPLE_DOCS`); every repo path in backticks exists. A **bounded allowlist** of
  read-only commands is executed via `subprocess.run` with `HOME` and `TMPDIR` pointed at
  `tmp_path`, exit 0 asserted: `uv run studyloop --version`, `uv run studyloop --help`,
  `uv run studyloop doctor --help`, `git log -1 --format='%h %s' <F14 sha>`. Never `just e2e`,
  never `just testacc`, never a session start, never network.
- **H — structure.** First non-heading block is a paragraph of ≤ 3 sentences or a numbered list;
  ≥ 1 numbered list; no H1 other than the title; line count ≤ the page's cap (150 for every
  page; 200 for the router, which carries 15 anchors; 220 for the testing cookbook, whose
  collected examples are code pinned by `test_contributor_docs.py` — assembler amendment after
  A0 measured it at 214); no `<!-- GUIDE-STUB -->` marker left.
- **L — links.** Every `[text](path.md)` and `[text](path.md#anchor)` to `docs/` resolves and the
  anchor exists (GitHub-style slug); the router's H2 set equals F10 exactly.
- **M — module pages.** Page 20: "design stage" within the first paragraph; a link containing
  `module-contract-v1/proposal.md`; no fenced line beginning `studyloop module` or
  `studyloop drill`; none of the present-tense phrases `is available`, `install it`, `the index
  lists` applied to the index. Page 19: "proposal" in the first paragraph.
- **F — facts.** The three §5 cross-page facts read from `harnesses.py`, `pyproject.toml` and a
  constant for F1, asserted against every page that mentions them.
- **Receipts.** `evidence/<writer>/commands.txt`: for each fenced command on the writer's pages,
  `$ <command>` / `exit=<n>` / first 5 output lines / `sha=<HEAD>` / `utc=<time>`. The test does
  not read receipts (they are evidence, not code); A1 does, and refuses a page whose fenced
  commands are not all receipted.

Red evidence: A0 commits `evidence/A0/red.txt` showing the test failing on all 15 stubs; each
writer's first commit for a page may carry its own `red.txt` if the page needed a new check.

## 7. Risks and gates

| Risk | Gate |
| --- | --- |
| Fabricated history on the PR page (two council seats did exactly this) | Only F14 shas; any addition needs a `git log -1` receipt; A1 re-runs every sha on the page |
| A command written but never run | C executes the allowlist; A1 refuses unreceipted fenced commands |
| The module index read as existing | M; the Click-tree test fails any fenced proposed command |
| Duplicated content across pages | A1 greps each H2 text across `docs/contributor-*.md`; a repeated H2 is a finding; the router links, never restates |
| Old links break | No moves; L pins the router's anchors and the root `CONTRIBUTING.md` paths |
| Walls of text | H line cap and answer-first rule; owner read |
| Two writers in one worktree | Four worktrees; A1's merges are file-disjoint by construction |
| Lease collision with lanes S3/W5 | Lease held from scaffold commit to merge; recorded in the module-contract ledger |
| The guide outruns the code (describes a command that lands later) | Pages describe `main` at the scaffold sha; proposed things are prose, labelled |

## 8. Review cadence (design.md §7 of module-contract applies: "when needed" plus milestones)

- **Council G1 — the finished guide**, after A1 and before the owner reads: four seats (`gpt-5.6-sol`,
  `deepseek-3.2`, `qwen3-coder-next`, `glm-5`), one fixed brief, each seat reads the built pages
  and the drift test and must cite `file:line` for every finding; the coordinator verifies each,
  fixes or records, and fills the catch-rate row. Seat weighting carries forward from the
  planning round (GLM and DeepSeek discounted on unverified claims).
- **Single-seat checks (when needed):** a writer reports a contradiction between two §3 facts, or
  a command the page needs that the repo lacks.
- **Owner:** reads §2 inventory and §4 standard first (the two decisions most likely to be
  amended), then the built site after G1.

## 9. Effort and critical path

Measured against today: a planning seat took 8-15 min; the module-contract plan's writers were
not yet timed. Estimate: A0 45 min; writers 60-100 min each in parallel (5 pages × run commands
+ write + receipt); A1 45-60 min; G1 ~20 min + fixes 30-60 min. **Wall clock ≈ 4-5 hours of
agent time today**, ≈ 15-20 agent-hours in total, then the owner's reading (≈ 90 min for
20 short pages) and the outside reader (DoD 7, Bruno or the second contributor, their time). The
binding constraint is the owner's read and the outside walk, not the writing.

## 10. Definition of done — mapping

| proposal DoD | Where it is met |
| --- | --- |
| 1 inventory in design.md | §2 (this file) |
| 2 every page written, strict build, in nav | A1 gate: `just docs`, nav in §2 |
| 3 PR page with ≥ 6 real examples + template | page 14 with eight F14 examples; `.github/PULL_REQUEST_TEMPLATE.md` |
| 4 drift test pins every command and path | `test_contributor_guide_drift.py` C/L + `_STUDYLOOP_EXAMPLE_DOCS` |
| 5 module index says design stage, links proposal | M pattern, page 20 |
| 6 council review, findings fixed/recorded, catch-rate filled | G1 |
| 7 outside reader walks Welcome on a clean machine | owner-scheduled after merge; evidence under `evidence/reader/` |

## 11. Writer briefs

`briefs/00-common.md` (the rules above, condensed), `briefs/A0-scaffold.md`, `briefs/W-A.md` …
`briefs/W-D.md`, each listing its pages from §2, the §3 facts it must cite, its example
candidates, the receipt format and the stop condition. Written by the coordinator in tasks 0.3.
