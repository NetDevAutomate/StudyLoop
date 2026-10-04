# Tasks — contributor guide v1

Plan: `design.md` (page inventory §2, facts sheet §3, writers §5, drift test §6). One commit per
page; pre-commit at commit time; `env -u VIRTUAL_ENV` before `just`/`uv`;
`export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"` before any test. Writers never run `just e2e`.

## 0. Setup (coordinator)

- [x] 0.1 Confirm the docs lease is free: `git -C <main> status --short` shows no uncommitted
      `docs/`, `mkdocs.yml` or `CHANGELOG.md`; record "lease held by contributor-guide-v1 from
      <scaffold sha>" in the module-contract ledger (S3, W5 queue).
- [x] 0.2 `git worktree add ../studyloop-wt/contributor-guide -b feat/contributor-guide main`;
      verify `git -C … rev-parse HEAD` equals `main`.
- [x] 0.3 Write `briefs/00-common.md`, `briefs/A0-scaffold.md`, `briefs/W-A.md` … `W-D.md`
      (design.md §11); verify each writer brief lists exactly its §5 pages and no shared file.

## 1. Scaffold (A0, one agent, `feat/contributor-guide`)

- [x] 1.1 Fifteen stub pages for every *new* page in design.md §2 (2-10, 13-16, 18, 20), each:
      `# <nav title>`, one-line purpose, `<!-- GUIDE-STUB -->`. Verify `ls docs/contributor-*.md`
      lists 20 files with the four seed pages.
- [x] 1.2 `mkdocs.yml`: 15 `!/…` allowlist lines + the §2 nav block replacing lines 112-117;
      `acceptance-testing.md` leaves the top level. Verify `env -u VIRTUAL_ENV just docs` strict
      passes with the stubs.
- [x] 1.3 `packages/studyloop/tests/test_contributor_guide_drift.py` per design.md §6 (C, H, L, M,
      F), parameterised over the inventory tuple; `_STUDYLOOP_EXAMPLE_DOCS` in `test_docs_drift.py`
      extended with the 16 new/extended pages. Verify the new test is **red on every stub** (the
      marker and the missing numbered list fail H) and green on nothing; save
      `evidence/A0/red.txt` (first line = command).
- [x] 1.4 Verify the existing suites still pass: `test_docs_drift.py`, `test_contributor_docs.py`,
      `test_docs_harness_tier_contract.py`; `just docs`. Commit (two commits: pages+nav; test+red).
      Report the scaffold sha.

## 2. Writers (W-A ∥ W-B ∥ W-C ∥ W-D, four worktrees branched from the scaffold sha)

Per page, in this order, one commit each:
- [x] 2.x.1 Run every command the page will show; write `evidence/<writer>/commands.txt` entries
      (`$ cmd` / `exit=` / 5 lines / `sha=` / `utc=`). A command that fails is not documented.
- [x] 2.x.2 Write the page to its §2 "one job"; cite §3 facts by number in an HTML comment at the
      top (`<!-- facts: F1 F3 F13 -->`) so A1 can audit; no `<!-- GUIDE-STUB -->` left.
- [x] 2.x.3 Verify `pytest packages/studyloop/tests/test_contributor_guide_drift.py -k <page>` green,
      `test_docs_drift.py` green, `just docs` strict green; commit page + receipt together:
      `docs(contributing): <page stem> — <one line>`.

Page sets (design.md §5): **W-A** contributing.md (router, anchors F10 kept), contributor-environment,
contributor-debugging, contributor-changelog, contributor-pull-requests (+ `.github/PULL_REQUEST_TEMPLATE.md`);
**W-B** contributor-cli, contributor-web, contributor-mcp, contributor-doctor; **W-C**
contributor-harnesses-agents, contributor-content, contributor-documentation, contributor-code-map,
contributor-conventions; **W-D** contributor-testing, acceptance-testing (cross-links only),
contributor-issues-prioritisation, contributor-ai, contributor-modules, contributor-module-index.

- [x] 2.W-A.pr The PR page carries exactly the eight F14 examples (or more, each with a `git log -1`
      receipt) and the normalised titles for PRs #40-#42; the template holds the five F3 questions.
- [x] 2.W-D.mi The module-index page passes M on its first commit; its 12 bullets are design.md §2's.
- [x] 2.end Each writer's final report: `git log --oneline <scaffold>..HEAD`, `git diff --stat`,
      pytest summary lines, `just docs` result, receipt line count, `git status --short` of the
      main checkout (nothing written there).

## 3. Assembly (A1, coordinator, `feat/contributor-guide`)

- [x] 3.1 Merge `feat/contributor-guide-a` … `-d` (fast-forward or merge commit each); verify
      `git diff --stat <scaffold>..HEAD` touches only the §2/§5 files.
- [x] 3.2 Receipt audit: every fenced command on every page appears in its writer's
      `commands.txt`; every sha on the PR page re-run with `git log -1 --format='%h %s'`.
- [x] 3.3 Cross-link and duplication pass: H2 text grep across `docs/contributor-*.md` (a repeated
      H2 is a finding); router links every owning page; `CONTRIBUTING.md` root links still resolve.
- [x] 3.4 `CHANGELOG.md` `[Unreleased]` → `### Added`: one learner-facing entry for the guide.
- [x] 3.5 Gates: `test_contributor_guide_drift.py` all green, `test_docs_drift.py` green,
      `env -u VIRTUAL_ENV just preflight` green, `just docs` strict green. Save summary lines under
      `evidence/A1/`. Commit.

## 4. Council G1 — the finished guide

- [x] 4.1 Coordinator writes the call into `council/catch-rate.md` (new row) BEFORE dispatch.
- [x] 4.2 Brief `council/<date>-review-brief.md`: read the 20 pages as built (`site/` or source),
      the drift test, the receipts; four questions — truth (every claim traceable to §3 or a
      receipt), reader journey (K6), naming page history (every sha), what the plan missed; every
      finding with `file:line`; ≤ 900 words; one output file per seat.
- [x] 4.3 Four seats dispatched in parallel; coordinator verifies each finding against the tree,
      fixes verified ones through the gates in 3.5, records the rest; fills the catch-rate row;
      writes `council/<date>-review-arbitration.md`.

## 5. Merge and release of the lease

- [ ] 5.1 Owner reads design.md §2 and §4 (objection window) — amendments applied before merge.
- [x] 5.2 (merged 6a3f45d2 before 5.1 — owner away; 5.1 becomes a post-merge objection window, amendments are ordinary docs(contributing) commits) `git merge --no-ff feat/contributor-guide` into local `main`; verify `just docs` and the
      three drift test files green on `main`; update the module-contract ledger: lease released,
      S3 and W5 unblocked.
- [ ] 5.3 Owner pushes `main`; owner schedules DoD 7 (Bruno or the second contributor walks
      *Welcome* on a clean machine); findings land as `docs(contributing)` fixes with evidence under
      `evidence/reader/`.
- [ ] 5.4 Archive this change to `openspec/changes/archive/<date>-contributor-guide-v1/` once DoD 7
      is recorded.

## 6. Follow-ups (not tasks here)

- A CI check that a PR title matches the §4 grammar (GLM's proposal) — a `ci(...)` change after
  the standard has been used for a few PRs.
- Issue templates under `.github/ISSUE_TEMPLATE/` matching page 15.
- A clean-machine docs build in CI (`docs.yml` already builds; confirm it runs strict).
