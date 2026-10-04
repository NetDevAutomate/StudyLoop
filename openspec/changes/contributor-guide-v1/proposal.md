# Proposal — a contributor guide for StudyLoop, modelled on the Terraform AWS Provider's

**Status:** proposed 2026-10-04 (owner request, 16:45 BST); council planning round in progress.
**Owner:** Andy Taylor. **Coordinator:** Kiro (default). **Change id:** `contributor-guide-v1`.

## Why

StudyLoop is about to take its first outside contributions (issue #53, a colleague; a second
core contributor joining). The repository is well set up for unit, integration, e2e,
acceptance and UAT testing and has a first contributor section (committed `71c09393`:
*Start Contributing*, *Code Map*, *Testing Cookbook*, *Optional Modules (Proposal)*), but a
new contributor still has to reverse-engineer conventions from history: how to name a branch
and a pull request, what a changelog entry looks like, which gate runs when, how to add a
harness adapter or an MCP tool, how documentation is kept truthful.

The owner's reference is the [Terraform AWS Provider Contributor Guide](https://hashicorp.github.io/terraform-provider-aws/)
— he was a contributor before the v2 SDK and knew it well. What made it good, in his words:
the numbered welcome path, contribution guides *per kind of change*, the testing pages, and
a clear *Raising a Pull Request* page with a naming standard. That is the bar.

## What

A `Contribute` section of the mkdocs site that a colleague can follow from clone to merged
PR without asking a maintainer, with **runnable examples on every page**, plus a
**Developer Reference** for the repository's own conventions. One new page describes the
**module index** at a high level and states plainly that it is at **design stage**
(`openspec/changes/module-contract-v1/proposal.md` §9; nothing exists yet).

## Constraints

- Every command shown is run before it is written and pinned by a docs-drift test, in the
  pattern `packages/studyloop/tests/test_docs_drift.py` already uses; a page without a test
  that would fail when the repo moves is not done.
- `mkdocs.yml` uses an `exclude_docs` allowlist: every new page needs its `!/…` line and a
  nav entry; the strict build must pass.
- Extend or restructure the four existing pages; never duplicate them. Proposed moves are
  stated explicitly and `test_docs_drift.py`'s link checks keep old paths valid or redirected.
- Nothing registry-shaped is built or implied as existing (module-contract design.md C8).
- AuDHD-friendly structure: short pages with one job each, numbered steps, the answer before
  the explanation, no walls of text.
- The docs lease (`docs/`, `mkdocs.yml`, `CHANGELOG.md`) is held by this change's lane while it
  writes; the module-contract lanes' docs tasks (S3, W5) queue behind it.

## Definition of done (countable)

1. The council-arbitrated page inventory exists in `design.md` with, per page: purpose, the
   Terraform page it mirrors (or "none"), exists/extend/new, and the examples it carries.
2. Every page in the inventory is written, builds under `just docs` strict, and is in nav.
3. A *Raising a Pull Request* page states the branch, commit-subject and PR-title standard
   with ≥ 6 worked examples drawn from real repository history, and a PR template matches it.
4. `test_docs_drift.py` (or a sibling) pins every command and path the new pages show.
5. The module-index page says "design stage" in its first paragraph and links the proposal.
6. A council review round has read the finished guide; every verified finding is fixed or
   recorded as accepted; the catch-rate row is filled.
7. One outside reader (Bruno or the second core contributor) follows *Welcome* end to end on a
   clean machine and reports where they got stuck — recorded as evidence, fixed if real.
