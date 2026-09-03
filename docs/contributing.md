# Contributing to StudyLoop

StudyLoop is a local-first, AuDHD-aware study tool: a learner sits with an AI mentor that teaches through
Socratic questioning, and the tool wraps that session in structure — plans, spaced review, a parking lot
for stray thoughts, a wind-down. This guide is the single reference for contributing to it: how the repository
is organised, how to set up, how changes are made and proven, and how pull requests are reviewed.

The project is a **pre-release (0.1.x)**. Five mentor harnesses are first-party: Kiro CLI, Codex and Claude
Code are core; OpenCode and pi are preview. Everything else is out of scope until an issue defines it.

Contributions of every kind are welcome: a reproducible bug, a clearer setup sentence, an accessibility
observation, a focused test, or an honest account of where a study flow became overwhelming. Read the
[AuDHD learning philosophy](audhd-learning-philosophy.md) first; it explains the design constraints that
shape every decision here.

## Contents

1. [Development environment](#development-environment)
2. [How the repository is organised](#how-the-repository-is-organised)
3. [Making changes](#making-changes)
4. [Testing](#testing)
5. [Continuous integration](#continuous-integration)
6. [Documentation standards](#documentation-standards)
7. [Changelog process](#changelog-process)
8. [Raising a pull request](#raising-a-pull-request)
9. [Submitting an issue](#submitting-an-issue)
10. [How we prioritise](#how-we-prioritise)
11. [AI usage, and models through a LiteLLM gateway](#ai-usage-and-models-through-a-litellm-gateway)
12. [Security](#security)
13. [FAQ](#faq)

## Development environment

Requirements: Python 3.12 or newer, [`uv`](https://docs.astral.sh/uv/), [`just`](https://github.com/casey/just),
`tmux` (for CLI study sessions and the integration suite), Node.js (for the JavaScript tests), and Chromium
via Playwright (for the browser suite).

```bash
git clone https://github.com/NetDevAutomate/StudyLoop.git studyloop
cd studyloop
uv sync --all-packages --all-extras
uv run playwright install chromium
uv run pre-commit install
```

The `Justfile` is the front door. The recipes you will use most:

| Recipe | What it does |
| --- | --- |
| `just sync-dev` / `just sync-web` / `just sync-full` | Sync the workspace venv with the dev group, plus the web extra, plus every extra. A **fresh worktree has no venv**; run one of these before any other recipe or pyright reports hundreds of unresolved imports. |
| `just test`, `just test-web`, `just test-js` | Unit suite, web unit suite, JavaScript unit tests. |
| `just lint`, `just typecheck` | ruff (line length 100, `py312`) and pyright (`basic`), over `src/` **and** `tests/`. |
| `just docs` | `mkdocs build --strict`. |
| `just spec-check` | `openspec validate --specs --all`; skips when the `openspec` CLI is missing. |
| `just preflight` | Everything above in one run: lint, typecheck, unit, JS, docs, release consistency, spec check. Run it before every push. |
| `just e2e` | The Playwright browser suite. It takes a machine-wide lock; **one e2e run per machine at a time**. |
| `just release-check` | The release gate: preflight plus dependency audits, a wheel build, a fresh-venv install smoke and a per-extra install smoke. |
| `just ci-local` | Mirrors the GitHub Actions matrix locally. |

Working from a git worktree? Prefix `just` and `uv run` with `env -u VIRTUAL_ENV` so the worktree's own venv is
used rather than the one exported by your shell.

## How the repository is organised

```text
studyloop/
├── packages/studyloop/            # learner-facing CLI, Web UI, mentor adapters, planning, review, content
├── packages/agent-session-tools/  # session import, SQLite search, sync, Obsidian mirroring
├── agents/                        # mentor personas, skills and protocols per harness; agents/shared/ is the methodology
├── docs/                          # the published guides (mkdocs.yml allowlist) plus docs/adr and docs/architecture
├── openspec/                      # capability specs (what the system does) and change proposals
├── scripts/                       # thin helpers used by the Justfile and CI
└── releases/                      # release notes
```

**Principles that decide where code goes.** The core study engine owns learner workflows; optional
integrations extend it and the core never depends on them. Presentation layers (CLI, Web UI, TUI) call
application services, never each other's private helpers. Live study sessions are the primary workflow;
flashcards and quizzes support it.

**Backends sit behind protocols.** Terminal multiplexers (`tmux`, `herdr`) implement the `Multiplexer`
protocol in `packages/studyloop/src/studyloop/multiplexer.py`; content providers are rows in a data registry
(`content/generators/provider_profiles.py`); mentor harnesses are adapters under `adapters/`. A new backend of
any of these kinds is a new implementation behind the existing interface, not a new code path through the core.

**Why the code looks the way it does** is recorded in two places that are public on purpose:

- [Architecture Decision Records](https://github.com/NetDevAutomate/StudyLoop/tree/main/docs/adr) — short,
  immutable records of the decisions a reasonable engineer could have made differently (`docs/adr/`). A changed
  mind is a new ADR that supersedes the old one, never an edit.
- The [session-authority contract](https://github.com/NetDevAutomate/StudyLoop/blob/main/docs/architecture/session-authority.md)
  and the [current architecture](https://github.com/NetDevAutomate/StudyLoop/blob/main/docs/architecture/current.md)
  in `docs/architecture/`. The contract is the document the session tests are written against.

Implementation plans, review evidence, handoffs and audits are **not** in the repository. They are maintained
privately and summarised here or in an ADR when a decision is worth keeping.

**Names.** Python modules are `snake_case`; documentation files are `kebab-case.md`; classes are nouns
(`AgentAdapter`), functions are verbs (`start_session`), protocols describe a capability (`Multiplexer`).
Use the domain vocabulary consistently: *study session* (learner with mentor), *body double* (presence
with low instructional pressure), *review artefact* (flashcard or quiz JSON), *source material* (the learner's
own notes and documents), *agent adapter* (launch/control of one harness), *session exporter* (imports a
harness's transcripts).

## Making changes

1. **Start from an issue for anything that changes behaviour.** For a new mentor harness the issue must
   define the persona mechanism, launch and resume commands, session store, exporter, health check, failure
   behaviour and a live acceptance path. Drive-by harness additions are declined.
2. **Branch from `main`** with a `feat/`, `fix/`, `docs/` or `test/` prefix. Do not use `lane/…`; that prefix
   is reserved for the maintainers' remediation lanes and carries an ownership test that only makes sense
   there. On any other branch that test is skipped.
3. **Specs before surprises.** Behaviour is described in `openspec/specs/<capability>/spec.md`; a change that
   alters behaviour comes with a proposal under `openspec/changes/<change>/` (proposal, design, tasks).
   `just spec-check` validates the specs. When a design decision will still matter in six months, write an
   ADR (`docs/adr/NNNN-kebab-title.md`, indexed in `docs/adr/README.md`) and have the design link to it.
4. **Tests first.** Write the failing test at the nearest useful boundary, watch it fail for the right reason,
   then make it pass. A fix without a test that would fail on revert is not finished.
5. **Docs in the same change.** Every user-visible change updates the relevant guide and the changelog in the
   same pull request. Documentation claims are tested (see below), so a stale sentence fails the build.
6. **Keep the diff focused.** One problem per pull request. If public behaviour and internal structure both
   have to move, split them unless one is meaningless without the other.
7. **Before pushing:** `just preflight`, then `git diff --check`. If you touched anything the browser exercises,
   `just e2e` as well.

Commit messages: an imperative subject line, and a body that says **why** (what was wrong, what the change
makes true), not a restatement of the diff. If an AI assistant helped write the change, say so with a
`Co-Authored-By:` trailer; you remain the author who reviewed and stands behind it.

## Testing

The suite is layered by what each layer can prove and what it needs from the machine.

| Layer | Marker / recipe | Proves | Needs |
| --- | --- | --- | --- |
| Unit | `just test` (default `pytest`) | Logic, contracts, protocol conformance, docs-truth guards | Nothing external |
| Integration | `pytest -m integration` | Real tmux and herdr sessions, real SQLite | tmux installed; herdr optional |
| Browser (e2e) | `just e2e` (`pytest -m e2e`) | The Web UI journeys against a real server with fake agents | Playwright Chromium; one run per machine |
| Live | `pytest -m live_kiro`, `pytest -m live_provider` | A real Kiro child, a real LLM provider | Credentials and quota; opt-in only |

**Rules that keep the suite honest.**

- Tests use isolated fixtures under `tmp_path`. Fixtures are never selectable as product backends and never
  ship in the wheel.
- The suite **fails the run** if a test touches the real `~/.config/studyloop` or leaves a session in the real
  tmux server. Spawned servers get an isolated `HOME`, `XDG_*` and `STUDYLOOP_SESSION_DIR`; the spawn helper
  refuses an environment that still points at your real directories. If a guard fires, the test is wrong, not
  the guard.
- Prove a new test is not vacuous: revert the fix locally and watch it fail, or say in the pull request why
  it cannot be reverted.
- Do not widen a timeout to fix a flaky test. Find the mechanism (a state event, a locator condition) and
  wait on that.
- Do not copy test totals into documentation. A guard rejects three-digit "N tests" claims in `docs/` and
  `releases/`; the executing gate is the only authority for numbers.

Focused runs while iterating:

```bash
env -u VIRTUAL_ENV uv run --group dev pytest packages/studyloop/tests/test_session_state.py -q
env -u VIRTUAL_ENV uv run --group dev pytest -m integration packages/studyloop/tests/test_harness_matrix.py -q
```

## Continuous integration

`ci.yml` runs on every push and pull request to `main`: lint, typecheck, SAST (bandit), dependency audits,
the unit suite on Python 3.12 and 3.13, the JavaScript tests, the browser suite, a wheel build with an install
smoke, and the web, content and semantic dependency profiles. A red job blocks merging; fix it or explain in
the pull request exactly which unrelated failure you are seeing and where it is tracked.

Two nightly workflows run on a fresh macOS runner: the **tmux integration UAT** (03:00 UTC, also triggerable
manually) and the **install check** (03:30 UTC). They catch what a developer machine hides: a hard-coded
path, a dependency that only resolves from the workspace, a lock file that drifted.

The dependency lock is enforced (`uv sync --locked`). If you change a dependency, run `uv lock`, commit
`uv.lock`, and confirm `uv lock --check` leaves the tree clean.

## Documentation standards

- **The published site is an allowlist.** `mkdocs.yml` names every public page. A new file under `docs/` is
  invisible to the site until it is written for readers and added to both the allowlist and the navigation.
  `docs/adr/` and `docs/architecture/` are public in the repository for the reasoning they carry.
- **Every documented claim must be true**, and the true ones are guarded: CLI examples in the reference are
  resolved against the real Click commands, prompt strings in the setup guide are checked against the wizard
  code, the break table is parsed and compared with the constants, third-party notices are counted against the
  vendored manifest. When you change behaviour, expect a docs test to fail until the page catches up.
- Write for a reader with limited attention: one idea per paragraph, the answer first, a Mermaid diagram
  where structure matters, commands in fenced blocks, no marketing.
- Third-party claims (a tool's behaviour, a licence, a price) are pinned to a dated source.
- Licences travel with the code. Anything vendored is listed in `web/static/vendor/MANIFEST` with a hash and
  credited in `THIRD-PARTY-NOTICES.md` with the licence text; borrowed ideas are credited at the point of use.

## Changelog process

`CHANGELOG.md` keeps an `[Unreleased]` section with `### Added`, `### Changed`, `### Fixed`, `### Removed`
and `### Security`. Write entries in the learner's terms ("starting a web session no longer clobbers a running
CLI session"), not the code's. Dependency bounds and packaging changes go under `Changed`. Do not date a
release or move `[Unreleased]`; the maintainer cuts releases.

## Raising a pull request

Before you open it: `just preflight` is green, `git diff --check` is clean, the branch has no merge-conflict
markers (a repository test scans for them), and the changelog entry is written.

The description answers five questions, briefly:

1. What learner or contributor problem does this solve?
2. What changed?
3. Which automated checks passed, and where?
4. Which live or manual journey did you check yourself?
5. What remains unverified?

Automated green and a manual check are separate claims; state both. Small pull requests are reviewed faster
and reverted more safely. Reviewers verify claims against the code rather than trusting the description, so
precise `file:line` references help.

## Submitting an issue

For a bug: what you were trying to do, the exact command or Web UI action, what happened and what you
expected, and the output of `studyloop doctor --json` with private paths removed. Say whether it reproduces
with Kiro CLI, the documented demo harness.

Never paste API keys, bearer tokens, session transcripts, or your full local configuration into an issue,
fixture, screenshot or log. Session content is the learner's private material.

For a feature: describe the learner situation first (energy level, what they were trying to do, where the
friction was), then the smallest change that would help. The philosophy page explains why "smaller" wins.

## How we prioritise

1. Anything that breaks or endangers a learner's session, data or privacy.
2. Friction in the first week: setup, first session, first review.
3. Truth of the documentation.
4. Accessibility and low-energy paths.
5. New capability, in the order the roadmap gives.

Issues are triaged within a few days. Reactions and clear reproductions move things up.

## AI usage, and models through a LiteLLM gateway

**Using an AI assistant to contribute** is welcome. Two conditions: you review and understand everything you
submit, and you disclose the assistance (`Co-Authored-By:` trailer or a line in the pull request). The
reviewer holds AI-written code to exactly the same bar: tests that fail on revert, docs that are true.

**Where models are chosen in StudyLoop.** There are two independent places, and neither is hard-coded to a
vendor:

1. *Mentor harnesses* (Kiro CLI, Codex, Claude Code, OpenCode, pi) bring their own model access. StudyLoop
   launches them and never sees their credentials. To route a harness through a gateway, configure the
   harness itself according to its own documentation.
2. *Content generation* (flashcards, quizzes) uses a provider registry in
   `packages/studyloop/src/studyloop/content/generators/provider_profiles.py`. Each entry binds a slug to an
   adapter (`openai_compat`, `anthropic_compat`, `bedrock`, `ollama`), a base URL, the environment variable
   that carries its key, and a curated model list. Shipped slugs: `openai`, `openrouter`, `gemini` (the API,
   not a mentor), `anthropic`, `bedrock` (SigV4 via your AWS profile), and `ollama` (the offline default).
   The active one is chosen by the top-level `card_generator:` block in `config.yaml` (`backend`, `provider`, `model`).

**A LiteLLM gateway** is an OpenAI-compatible proxy that fronts many providers behind one URL and one key.
Because the registry already has an `openai_compat` adapter, adding one is the documented extension:
one `ProviderProfile` row (`adapter="openai_compat"`, `base_url` of your proxy, an `auth_env` such as
`LITELLM_API_KEY`), a curated model list, and a line in `.env.example`. Two honest caveats before you do:
today a row's base URL is fixed in the registry, so a per-machine proxy address needs an environment
override that does not exist yet — open an issue and propose it there first; and keys named `*_API_KEY`,
`*_TOKEN`, `*_SECRET` are deliberately scrubbed from every process StudyLoop spawns
(`session/child_env.py`), so a gateway key set for StudyLoop never reaches a mentor child. That is a feature.

**How the maintainers use one.** Plans and large changes are reviewed by three or four models from different
families through a LiteLLM gateway before a human reads them: each model gets the same brief, works in
isolation, and every load-bearing claim it makes is checked against the source before it counts. The
arbitration is recorded with the change. Contributors do not need this — CI and human review are the gate — but
if you run your own multi-model review, keep keys and transcripts out of the pull request and cite the
verified findings, not the model's opinion.

## Security

Report vulnerabilities privately through
[GitHub's advisory form](https://github.com/NetDevAutomate/StudyLoop/security/advisories/new); see
[`SECURITY.md`](https://github.com/NetDevAutomate/StudyLoop/blob/main/SECURITY.md) for the supported line
and the model. In code: secrets live in the encrypted store, never in `config.yaml` or the repository; the
LAN password reaches the web process through its environment, not argv; test hatches that replace the agent
binary are snapshotted at import and refused when they arrive from a `.env`. Pre-commit runs secret detection
and bandit; keep them installed.

## FAQ

**Can I add support for my favourite coding assistant?** Open an issue with the seven items listed under
*Making changes*. A harness is a contract with a live acceptance path, not a launcher.

**The docs build failed on a sentence I did not write.** Your change made that sentence false. Fix the
page; that is the point of the guard.

**`just e2e` says another run holds the lock.** Wait for it, or find the stale lock the recipe reports. Two
browser suites on one machine collide on ports and produce false failures.

**Where are the design notes for X?** In an ADR if the decision was load-bearing, in the module docstring if
it was local, and in the maintainers' private archive otherwise. Ask in an issue; if the answer is worth
keeping, it becomes an ADR.

**I only have low-energy time.** Documentation truth fixes, reproducible bug reports and accessibility notes
are the most valuable small contributions this project receives.
