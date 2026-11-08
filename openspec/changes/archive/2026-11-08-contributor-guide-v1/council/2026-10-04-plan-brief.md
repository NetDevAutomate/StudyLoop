# Council brief — plan the StudyLoop contributor guide (planning round, 2026-10-04)

You are one of four independent planning seats. Answer **every** numbered question below,
countably, in order, in ≤ 1,500 words. Write your answer to the file named in your dispatch
message and nothing else; do not touch any other file. You may read the whole repository
(read-only) and fetch the reference site. Cite paths with line numbers for every repository
fact you rely on; cite the reference page URL for every pattern you borrow.

## What is being planned

A contributor guide for StudyLoop (Python/uv/FastAPI/Alpine, mkdocs site, six supported AI
harnesses) of the quality of the **Terraform AWS Provider Contributor Guide**
([index](https://hashicorp.github.io/terraform-provider-aws/)). The owner contributed to that
provider before its v2 SDK and names what made the guide good: the numbered *Welcome* path
(configure environment → debug → change code → write tests → CI → changelog → pull request),
contribution guides **per kind of change**, dedicated acceptance/unit test pages, a
*Changelog Process* page, and *Raising a Pull Request* with a clear **naming standard**.
Read, at minimum: the index, *Raising a Pull Request*, *Naming Standards*, *Changelog
Process*, *Development Environment*, *Acceptance Tests*, *Documentation Changes*,
*Add a New Resource Type*, *How We Prioritize*, *FAQ* (nav links on the index page).

The proposal is `openspec/changes/contributor-guide-v1/proposal.md`; its definition of done
is binding. The guide is written by parallel agents after this round, then reviewed by a
second council round; your plan decides how the writing is split.

## Hard constraints — settled, not up for review

- K1. Every command a page shows is run before it is written and **pinned by a docs-drift
  test** (`packages/studyloop/tests/test_docs_drift.py`, 613 lines, 8 tests — read how it
  pins commands, headings and links). A page without a drift test is not done.
- K2. `mkdocs.yml` `exclude_docs` is an allowlist (`**` then `!/page.md`, lines 59+); ADRs,
  plans and agent instructions are deliberately **excluded** from the site. New pages need an
  un-exclude line and a nav entry; `just docs` runs strict.
- K3. The four existing Contribute pages (committed `71c09393`: `docs/contributing.md`,
  `docs/contributor-code-map.md`, `docs/contributor-testing.md`,
  `docs/contributor-modules.md`, plus `CONTRIBUTING.md` at the root) are the seed. Extend or
  restructure; **never duplicate**. If you move a page, say what keeps its old links valid.
- K4. **Nothing registry-shaped exists.** The module index page must say "design stage" in its
  first paragraph and link `openspec/changes/module-contract-v1/proposal.md` §9. The module
  *contract* is also still a proposal (`proposal.md` there) — describe both as proposed.
- K5. Branch names are `feat/…`, `fix/…`, `docs/…`, `test/…` (`docs/contributing.md:175-177`);
  `lane/…` is reserved. Maintainers merge with a merge commit. This is settled; the PR *title*
  and commit-subject standard is **not** yet written down — that is yours to propose (Q2).
- K6. AuDHD-friendly: short pages with one job, numbered steps, answer first, no walls of text,
  no "see elsewhere" loops. The owner is a senior engineer new to Python/data engineering;
  the first readers are a colleague (Kubernetes/Go background) and a developer new to this repo.
- K7. Agents' local git is free; pushes are the owner's. The docs lease: this guide's lane holds
  `docs/`, `mkdocs.yml`, `CHANGELOG.md` while writing; two other lanes queue behind it.

## Verified repository facts (cite more if you find them)

- F1. Gates: pre-commit (`.pre-commit-config.yaml`: whitespace, yaml, large files, private
  key, AWS creds, ruff, ruff-format, detect-secrets, bandit, commit-author check, AWS-token
  check, trufflehog, pyright on `packages/**/*.py`) at the **commit** stage; `just preflight` =
  `lint typecheck test test-js docs release-consistency spec-check` (`justfile:279`);
  `just e2e` holds a machine-wide lock (`justfile:64-68`). CI: `.github/workflows/ci.yml`,
  `docs.yml`, `nightly-install.yml`, `nightly-uat.yml`. **No** PR or issue templates exist
  under `.github/` yet.
- F2. Commit subjects in the last 300 commits are conventional-commit shaped: `docs` 106,
  `test` 91, `fix` 49, `feat` 37, `chore` 6, `ci` 1, plus merge commits
  `Merge PR #NN (branch): subject`. Scopes seen: `now`, `web`, `openspec`, `plan`, `mcp`,
  `agents`, `session`, `doctor`, `learning-tier`, `verify`, `spec`, … (`git log --format=%s`).
- F3. Test tiers: default (offline; `addopts` deselects `integration e2e live_* acceptance uat`,
  `pyproject.toml:98`), `integration`, `e2e` (Playwright, `tests/e2e/_env.py` hermetic world),
  `acceptance` (`just testacc`, `STUDYLOOP_ACC=1`), `uat` (`just testuat`,
  `STUDYLOOP_ACC=1 STUDYLOOP_UAT=1`), live lanes. `docs/acceptance-testing.md` and
  `docs/contributor-testing.md` describe them.
- F4. Six supported harnesses, exactly: kiro-cli, claude code, codex, opencode, pi, grok
  builder (`adapters/{kiro,claude,codex,opencode,pi,grok}.py`, `registry.py`);
  `test_adapter_parity.py` and `test_docs_harness_tier_contract.py` pin parity. Harness
  additions are currently declined (`docs/contributing.md:170`).
- F5. Kinds of change a contributor actually makes here (the analogue of Terraform's
  resource/data-source/service): a CLI command (`cli/_*.py`, Typer), a web route + static UI
  (`web/routes/`, `web/static/`), an MCP tool (`mcp/`), an adapter (declined for now), an
  agent prompt/skill (`agents/shared/`, `agents/<harness>/`), content schemas and pipeline
  (`content/`), a doctor check (`doctor/`), docs. Verify each path.
- F6. `CHANGELOG.md` is Keep-a-Changelog shaped with an `[Unreleased]` section and `### Added`
  etc.; `just release-consistency` checks it against version metadata (read the recipe).
- F7. OpenSpec changes live under `openspec/changes/<id>/` with `proposal.md`, `design.md`,
  `tasks.md`, `specs/`; `just spec-check` validates them. Specs are "the description of
  behaviour, the tests are the proof" (`docs/contributing.md:179-180`).
- F8. ADRs under `docs/adr/` with an index table in `docs/adr/README.md`; excluded from the site.
- F9. The owner has asked that agents producing docs **run every command they document**; the
  previous contributor pages were caught claiming commands that did not exist
  (`session-query search` vs `search-cmd`) — the drift tests exist because of that.

## Questions — answer every one, countably, in this order

1. **Page inventory.** A table: StudyLoop page (path under `docs/`) · purpose in one line ·
   Terraform page it mirrors (URL) or "none" · exists / extend / new · the runnable examples it
   carries (≥ 1 per page) · the drift test that pins it. Group into *Welcome*, *Contribute*
   (per kind of change, F5), *Testing*, *Process* (changelog, PR, issues, prioritisation, AI
   usage), *Developer Reference*, *Proposals* (module contract, module index — design stage).
   Target 14–22 pages; justify anything outside that range. Say which existing pages move.
2. **Naming standard** for branches, commit subjects and PR titles, derived from F2 and K5,
   with ≥ 6 worked examples taken from **real** recent commits/PRs (cite shas/PR numbers) and
   the rule for scopes (closed list or open? how `docs(openspec)` vs `docs(contributing)` is
   decided). Include what a PR description must contain and how a PR maps to a changelog line.
3. **Changelog process**: who writes the entry, when, which section, how `release-consistency`
   is satisfied, one example diff.
4. **The module index page**: outline (≤ 12 bullets) that is useful to a would-be module author
   today while saying plainly nothing is built; what it must not promise.
5. **Truthfulness mechanism**: which drift-test patterns to add (commands run via subprocess
   with asserted output? heading presence? link validity?), and how a writer proves "I ran it".
6. **Parallel writing plan**: how many writer agents, the disjoint file ownership per writer,
   the single assembler's job (nav, allowlist, cross-links, drift tests), and the order so no
   two writers touch one file. Name the three cross-page facts most likely to be stated
   inconsistently and how the assembler checks them.
7. **Risks** with a detection gate each (e.g. duplicated content, commands not run, module
   index read as existing, nav sprawl, AuDHD rules violated).
8. **Where the other seats will be wrong** — the two claims you expect them to make that the
   repository contradicts, with citations.
9. **What this brief gets wrong** — anything above the repository contradicts.

## Rules

Read before you plan: the four existing pages, `test_docs_drift.py`, `mkdocs.yml`, `justfile`,
`docs/contributing.md`, `.github/workflows/ci.yml`, and the reference pages named above.
Facts come from the tree and the reference site, not from memory. Prefer fewer pages done
well to more pages done thinly. The decisions are the owner's; your job is a plan he can
accept or amend line by line.
