# Contributing to StudyLoop

<!-- facts: F1 F2 F3 F7 F8 F10 F13 -->

StudyLoop is a local-first, AuDHD-aware study tool, pre-1.0, and every kind of contribution is
welcome — a reproducible bug, a clearer sentence, a focused test, an honest account of where a study
flow became overwhelming. The path from clone to merged pull request is six steps; this page is the
router, and each step links the one page that owns it.

1. **Set up** — install uv, just, tmux, Node and Chromium, `just sync-dev`, prove the import:
   [Development Environment](contributor-environment.md).
2. **Make one change** — fork, branch as `docs/…`, `fix/…`, `test/…` or `feat/…`, change one
   thing: [Your first contribution](#your-first-contribution) below, then the page for your kind of
   change under [Making changes](#making-changes).
3. **Prove it** — the failing test first, at the nearest useful boundary, then the fix:
   [Testing Cookbook](contributor-testing.md). Stuck? [Debugging](contributor-debugging.md).
4. **Pass the gate** — `just preflight` (lint, typecheck, test, test-js, docs, release-consistency,
   spec-check; F7), `git diff --check`, and `just e2e` if you touched the web layer.
5. **Write the changelog bullet** — one learner-facing line under `[Unreleased]`, in the same PR:
   [Changelog Process](contributor-changelog.md).
6. **Open the pull request** — `<type>(<scope>): <imperative description>` as title, the five
   questions as description: [Raising a Pull Request](contributor-pull-requests.md).

**Licensing and conduct.** Contributions are accepted under the repository's
[MIT License](https://github.com/NetDevAutomate/StudyLoop/blob/main/LICENSE) (inbound = outbound;
no CLA, no DCO). The [Contributor Covenant 2.1](https://github.com/NetDevAutomate/StudyLoop/blob/main/CODE_OF_CONDUCT.md)
applies; beyond it, never quote learners' private material (transcripts, notes, struggles) in public.
Before you design anything, read the [AuDHD learning philosophy](audhd-learning-philosophy.md).

## Contents

1. [Development environment](#development-environment)
2. [Your first contribution](#your-first-contribution)
3. [How the repository is organised](#how-the-repository-is-organised)
4. [Making changes](#making-changes)
5. [Testing](#testing)
6. [Continuous integration](#continuous-integration)
7. [Documentation standards](#documentation-standards)
8. [Changelog process](#changelog-process)
9. [Raising a pull request](#raising-a-pull-request)
10. [Submitting an issue](#submitting-an-issue)
11. [How we prioritise](#how-we-prioritise)
12. [AI usage, and models through a LiteLLM gateway](#ai-usage-and-models-through-a-litellm-gateway)
13. [Security](#security)
14. [FAQ](#faq)

## Development environment

Python 3.12 (`.python-version`), uv, just, tmux, Node and Playwright Chromium; one `just sync-dev`;
then prove `import studyloop` resolves inside your checkout. Every command, with its output, is on
[Development Environment](contributor-environment.md).

## Your first contribution

You do not need to fix an entire workflow: a clearer sentence or a test for one refused operation is
a useful first PR. For a new capability, open an issue and agree the smallest slice before coding.

1. **Fork** StudyLoop on GitHub into your account and clone the fork
   (`git clone https://github.com/<you>/StudyLoop.git`). The upstream repository is
   `NetDevAutomate/StudyLoop`.
2. **Point at upstream and branch** from its `main`; choose `fix/`, `test/` or `feat/` instead of
   `docs/` when that is what you are changing (F1):

```bash
git remote add upstream https://github.com/NetDevAutomate/StudyLoop.git
git fetch upstream
git switch -c docs/first-contribution upstream/main
```

3. **Set up and change one thing.** Follow [Development Environment](contributor-environment.md),
   reproduce the problem with synthetic data, find the owning layer in the
   [code map](contributor-code-map.md), and change only that.
4. **Prove and open.** `git push -u origin docs/first-contribution` publishes **your fork branch**;
   GitHub then offers a PR into `NetDevAutomate/StudyLoop:main`. Report setup failures rather than
   bypassing checks or describing skipped tests as passing.

Before a second contribution, fetch upstream and branch afresh; do not stack unrelated changes on
your first PR, and never discard uncommitted work to synchronise a branch.

## How the repository is organised

Two packages (`packages/studyloop/` — CLI, Web UI, mentor adapters, planning, review, content;
`packages/agent-session-tools/` — session import, SQLite search, sync), `agents/` (personas and
skills per harness), `docs/`, `openspec/` (specs and change proposals), `scripts/`, `releases/`.
Which layer owns what, and where each kind of change lands: [Code Map](contributor-code-map.md).
Code-level naming, OpenSpec changes and ADRs: [Conventions](contributor-conventions.md).

## Making changes

Small fix: open the PR directly. Behaviour or design change: an issue first, then a proposal under
`openspec/changes/`. New mentor harness: declined unless an issue defines all seven items — persona
mechanism, launch and resume commands, session store, exporter, health check, failure behaviour, a
live acceptance path (F2; [Harnesses and Agents](contributor-harnesses-agents.md)). Then pick the
page for your kind of change:

1. [A CLI Command](contributor-cli.md) · 2. [A Web Route and UI](contributor-web.md) ·
   3. [An MCP Tool](contributor-mcp.md) · 4. [A Doctor Check](contributor-doctor.md) ·
   5. [Harnesses and Agents](contributor-harnesses-agents.md) ·
   6. [Content Schemas and Pipeline](contributor-content.md) ·
   7. [Documentation](contributor-documentation.md).

Branches are `feat/…`, `fix/…`, `docs/…`, `test/…`; `lane/` is reserved (F1). Commit subjects
follow the grammar on [Raising a Pull Request](contributor-pull-requests.md). Topic-specific
practice modules are a design-stage proposal, not a plugin API you can build against today:
[Optional Modules (Proposal)](contributor-modules.md) and
[Module Index (Proposal)](contributor-module-index.md).

## Testing

The default `just test` runs the unit tier; `integration`, `e2e`, `acceptance`, `uat` and the live
markers are deselected (F7). Choosing the tier and writing the focused test:
[Testing Cookbook](contributor-testing.md). Opt-in runs with a real harness:
[Acceptance Testing](acceptance-testing.md).

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request to `main` (lint, typecheck, SAST,
audits, the unit suite on 3.12 and 3.13, JavaScript tests, the browser suite, a wheel smoke); a red
job blocks merging. `.github/workflows/nightly-uat.yml` runs the *integration* tier nightly at
03:00 UTC; acceptance and UAT never run in CI (F8). Reproduce CI locally with `just ci-local`.

## Documentation standards

The site is an allowlist (`mkdocs.yml`), the build is strict, and claims are machine-checked —
a stale sentence fails the build. Writing a truthful page, and the AuDHD writing rules:
[Documentation](contributor-documentation.md).

## Changelog process

One bullet per user-visible change under `## [Unreleased]` in `CHANGELOG.md`, in the learner's
words, in the same PR; the maintainer dates it at release. Sections, wording and what the gate does
and does not check: [Changelog Process](contributor-changelog.md).

## Raising a pull request

Title `<type>(<scope>): <imperative description>`; description answers the five questions (F3):
problem, change, automated checks, manual check, what remains unverified. Grammar, eight real
examples, the template and what reviewers check: [Raising a Pull Request](contributor-pull-requests.md).

## Submitting an issue

Bug: what you tried, the exact command or UI action, what happened, what you expected, and
`studyloop doctor --json` with private paths removed. Feature: the learner situation first, then the
smallest change that would help. Never paste keys, tokens or session transcripts. Details:
[Issues and Prioritisation](contributor-issues-prioritisation.md).

## How we prioritise

1. A learner's session, data or privacy at risk. 2. Friction in the first week. 3. Truth of the
documentation. 4. Accessibility and low-energy paths. 5. New capability, in roadmap order. The
reasoning: [Issues and Prioritisation](contributor-issues-prioritisation.md).

## AI usage, and models through a LiteLLM gateway

AI-assisted contributions are welcome if you review everything you submit and disclose the help
(`Co-Authored-By:` trailer or a line in the PR). Mentor harnesses bring their own model access;
content generation uses the provider registry, where a LiteLLM gateway is one `openai_compat` row.
Disclosure, ownership and the gateway option: [AI Usage](contributor-ai.md).

## Security

Report vulnerabilities privately through
[GitHub's advisory form](https://github.com/NetDevAutomate/StudyLoop/security/advisories/new);
[`SECURITY.md`](https://github.com/NetDevAutomate/StudyLoop/blob/main/SECURITY.md) names the
supported line. In code: keys live in the encrypted store, never in the repository; pre-commit runs
secret detection and bandit — keep the hooks installed.

## FAQ

**Can I add my favourite coding assistant?** Open an issue with the seven items;
[Harnesses and Agents](contributor-harnesses-agents.md) explains why drive-by additions are declined.

**The docs build failed on a sentence I did not write.** Your change made it false; fix the page.
[Documentation](contributor-documentation.md).

**`just e2e` says another run holds the lock.** Wait, or check the pid it names:
[Debugging](contributor-debugging.md#5-just-e2e-says-another-run-holds-the-lock).

**I only have low-energy time.** Documentation truth fixes, reproducible bug reports and
accessibility notes are the most valuable small contributions this project receives.
