# Changelog Process

<!-- facts: F6 F7 -->

You write the changelog entry yourself, in the same pull request as the change, as one bullet in
the learner's words under `## [Unreleased]` in `CHANGELOG.md`; the maintainer dates it at release.
Nothing in the gates checks that bullet for you — `just release-consistency` reads version metadata
and the release note, not `[Unreleased]` — so the reviewer does, against question 2 of your PR.

## 1. Write the entry before review

1. Open `CHANGELOG.md` and find `## [Unreleased]` (the first heading after the preamble).
2. Pick the section from the table below. If the heading is missing, add it in this order:
   `### Added`, `### Changed`, `### Fixed`, `### Security`, `### Removed` — the order the
   `[0.5.0]` entry already uses.
3. Add **one bullet per user-visible change**, written for the learner: what they can now do, or
   what no longer goes wrong, in a sentence they would recognise. Say *what is true now*, not
   which function changed.
4. Reference the issue when there is one (`(issue #30)`), never a sha — bullets outlive branches.
5. Do not date anything and do not rename `[Unreleased]`; do not add sections outside the five.

| Commit type | Section | Notes |
| --- | --- | --- |
| `feat` | Added | a capability a learner did not have before |
| `fix` | Fixed | something that went wrong and now does not |
| a behaviour change | Changed | an existing flow does something different; dependency bounds and packaging changes also go here |
| a removal | Removed | a command, option or page that is gone |
| a security fix | Security | say what was exposed in neutral terms |
| `test`, `docs`, `chore`, `ci` | none, normally | the PR says so under question 2 ("no changelog entry: contributor-facing only") |

An internal refactor with no learner-visible effect gets no bullet; a docs change to a *learner*
guide (setup, troubleshooting) may deserve a Changed bullet. When unsure, write the bullet and let
the reviewer strike it — a missing bullet is harder to notice than an extra one.

## 2. The wording test

Read your bullet as the learner would. Two versions of the same (illustrative) fix for a commit
`fix(web): starting a web session no longer clobbers a running CLI session`:

- Not this: *Fixed race in `web/routes/session.py` where `start_session` ignored the tmux lock.*
- This: *Starting a web session no longer closes a CLI study session that is already running.*

Keep file paths, function names and test names out of the bullet unless the learner types them.
Numbers are the one exception the gates enforce: a three-digit "N tests" claim anywhere in
`CHANGELOG.md` fails `packages/studyloop/tests/test_docs_no_hardcoded_test_counts.py`, because the
executing gate is the only authority for test counts.

## 3. One example diff

```diff
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ ## [Unreleased]
 ### Fixed

+- Starting a web session no longer closes a CLI study session that is already
+  running; the web start now waits for the session lock instead of taking it.
 - Web voice plays again. From 2 September the page's security policy
```

Two lines, wrapped at the column the surrounding bullets use, inserted at the top of the section
so the newest change reads first.

## 4. What `just release-consistency` really checks

```bash
just release-consistency
```

The recipe is `uv run python scripts/check-release-consistency.py --skip-wheel` (F6). In this
ordinary mode it checks four things and prints `release consistency passed for studyloop 0.5.0`:

1. The version in `packages/studyloop/pyproject.toml` is a string, and the root `pyproject.toml`
   agrees with it.
2. `releases/v<version>.md` exists and its first heading names `v<version>`.
3. No ADR older than the latest tag still says *Proposed* (`docs/adr/`).
4. Nothing about `CHANGELOG.md`. The check that the version's dated changelog heading is on or
   after the git tag's date, and that the tag exists, lives in `validate_release_tag`
   (`scripts/check-release-consistency.py`, lines 300-336) and runs **only with `--release`** —
   `just release-consistency-shipped` adds `--release --pre-tag` and defers the tag assertion;
   `just release-verify` runs it for real after the tag is cut. It is part of `just preflight`
   (F7), so a wrong version or a missing release note fails your pre-push run; a missing or badly
   worded bullet does not.

That gap is deliberate and documented here so nobody assumes the gate covers the entry. The
reviewer checks the bullet against question 2 of the
[pull request](contributor-pull-requests.md).

## 5. What happens at release (maintainer only)

The maintainer runs `just prepare-release <version>` (bumps both `pyproject.toml` files and writes
the `releases/v<version>.md` skeleton; it does not touch the changelog), then by hand turns
`## [Unreleased]` into `## [<version>] - <date>`, opens a fresh empty `## [Unreleased]` above it,
writes the release note, tags, and runs `just release-verify`. Contributors never do any of this;
if your PR arrives while a release is being cut, the maintainer moves your bullet.
