# Contributing

How to set up a development environment, add features, and submit changes.

## Table of Contents

- [Development Setup](#development-setup)
- [Task Runner](#task-runner)
- [Code Style](#code-style)
- [Running Tests](#running-tests)
- [Release Build](#release-build)
- [Project Structure](#project-structure)
- [Spec-Driven Changes (OpenSpec)](#spec-driven-changes-openspec)
- [How to Add a New Session Exporter](#how-to-add-a-new-session-exporter)
- [How to Add a New Study Topic](#how-to-add-a-new-study-topic)
- [How to Modify Agent Behaviour](#how-to-modify-agent-behaviour)
- [Pull Request Process](#pull-request-process)
- [Code of Conduct](#code-of-conduct)

## Development Setup

```bash
git clone https://github.com/Hookey-Street-Software/StudyLoop.git studyloop
cd studyloop

# Install all packages with dev dependencies
uv sync --all-packages --group dev --all-extras

# Install pre-commit hooks
uv run pre-commit install
```

Pre-commit runs automatically on each commit:
- `ruff` — linting and formatting
- `trailing-whitespace`, `end-of-file-fixer` — file hygiene
- `detect-secrets`, `detect-private-key`, `detect-aws-credentials` — security checks

## Task Runner

Contributor workflows are exposed through `just`:

```bash
just test
just lint
just typecheck
just docs
just build-release
just release-check
```

Install `just` if needed:

```bash
brew install just
```

`just release-check` runs the full local release gate, in this order:
- `test` — the default `pytest` selection (no `e2e`, no `integration`)
- `lint` — `ruff check` and `ruff format --check`
- `typecheck` — pyright
- `shellcheck` — the four shipped shell scripts
- `docs` — `mkdocs build --strict`
- `audit` and `audit-full` — `pip-audit` on the default and all-extras exports
- `release-consistency` — release note matches the package version
- `smoke-installed` — builds the release artefacts, then installs and smoke-tests
  the wheel in a temporary venv

It does **not** run `spec-check`. Use `just preflight` when a change touches
`openspec/`.

## Code Style

- **Linter/formatter**: [ruff](https://docs.astral.sh/ruff/) (configured in each `pyproject.toml`)
- **Type checker**: [pyright](https://github.com/microsoft/pyright) in basic mode
- **Line length**: 100 characters
- **Target**: Python 3.12+ (both studyloop and agent-session-tools)

Run checks manually:

```bash
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run ruff format .             # Auto-format
uv run pyright packages/         # Type check
```

Key conventions:
- Type hints on all public functions
- Docstrings on all public functions and classes
- No bare `except:` — always catch specific exceptions
- No mutable default arguments
- Use `Path` objects, not string paths

## Running Tests

```bash
# Run all tests
just test

# Run with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest packages/agent-session-tools/tests/test_sync.py

# Run tests matching a pattern
uv run pytest -k "test_search"
```

Tests live in:
- `packages/studyloop/tests/` — studyloop CLI and review tests
- `packages/agent-session-tools/tests/` — session tools tests

### Playwright e2e and layout tests

Browser tests are marked `@pytest.mark.e2e` and **excluded from the default run**
(`pytest` addopts deselect them). Run them explicitly:

```bash
uv run pytest packages/studyloop/tests/ -m e2e
```

The e2e suites spawn a real `studyloop web` subprocess via
`sys.executable -m studyloop.cli`. **They serve the editable install's static
assets, so a stale install serves stale HTML/CSS/JS.** Before running e2e tests
(or verifying any UI change by hand), reinstall:

```bash
uv run studyloop install tools --skip-sync
```

(or the raw equivalent: `uv tool install --reinstall --editable
'./packages/studyloop[all]' --with-editable ./packages/agent-session-tools`)

A red e2e test whose actions pass when reproduced manually against a fresh
server is almost always a stale install — reinstall before suspecting the code.

### UI verification protocol (visibility ≠ layout)

DOM-presence assertions (`is_visible()`, `text_content()`) are **blind to visual
layout**: two elements can both be "visible" with correct text while overlapping,
clipped, or wrapped. Functional e2e tests will pass on a visibly-broken page.

When changing any UI surface (CSS, templates, view structure), add or update a
**geometry** assertion in `packages/studyloop/tests/test_web_layout_regression.py`
using the helpers in `tests/_layout_assertions.py`:

- `assert_stacked_no_overlap(upper, lower)` — title above description, no overlap
- `assert_within_viewport(selector)` — not clipped past the fold / right edge
- `assert_scroll_reachable(selector, container)` — tall content scrolls, not clipped
- `assert_hidden_when_class_present(selector)` — toggle-class actually hides
- `assert_centered_in(child, container)` — flex spacers balance the row
- `assert_single_line(container, child)` — no unintended wrapping
- `assert_nonzero_size(selector)` — controls aren't collapsed

Each helper documents the real bug class it catches. **Prove a new layout
assertion is real**: temporarily revert the fix and confirm the test goes red
(an assertion that can't fail guards nothing). Helpers select the first *visible*
match because views are kept in the DOM and toggled via `x-show` (shared classes
like `.nav-bar` appear in multiple hidden view subtrees).

## Release Build

Use the shared release-build script for local package verification:

```bash
just build-release
```

This recipe calls `./scripts/build-release.sh`, which:
- deletes old contents from `dist/`
- builds the `studyloop` sdist and wheel with `uv build --package studyloop --no-sources`

The release workflow uses the same script, so local and CI builds follow the same path.

## Project Structure

```
studyloop/
├── packages/
│   ├── studyloop/                    # User-facing study toolkit
│   │   ├── src/studyloop/
│   │   │   ├── adapters/           # Claude, Codex, Gemini, Kiro, OpenCode, local-LLM adapters
│   │   │   ├── cli/                # Click command surface
│   │   │   ├── content/            # NotebookLM and PDF processing
│   │   │   ├── doctor/             # Diagnostics and auto-fix checks
│   │   │   ├── history/            # Study session persistence helpers
│   │   │   ├── logic/              # Functional-core orchestration helpers
│   │   │   ├── mcp/                # studyloop MCP server/tooling
│   │   │   ├── services/           # Review/content service wrappers
│   │   │   ├── session/            # tmux startup, rollback, resume, cleanup
│   │   │   ├── tui/                # Textual sidebar
│   │   │   ├── web/                # FastAPI routes and static assets
│   │   │   ├── installers.py       # Typed install helpers used by CLI/doctor
│   │   │   ├── review_db.py        # Flashcard scheduling DB
│   │   │   └── settings.py         # Shared config loading
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── agent-session-tools/         # Session intelligence and export tooling
│       ├── src/agent_session_tools/
│       │   ├── exporters/           # Per-tool exporters
│       │   ├── integrations/        # Git/editor integration helpers
│       │   ├── export_sessions.py   # Export CLI
│       │   ├── query_sessions.py    # Query/write CLI
│       │   ├── query_logic.py       # Search/context helpers
│       │   ├── sync.py              # Cross-machine sync
│       │   ├── maintenance.py       # DB maintenance CLI
│       │   ├── mcp_server.py        # FastMCP server
│       │   ├── migrations.py        # Schema migrations
│       │   └── schema.sql           # Base SQLite schema
│       ├── tests/
│       └── pyproject.toml
├── agents/
│   ├── claude/                      # Claude Code agent assets
│   ├── codex/                       # Codex AGENTS.md source
│   ├── gemini/                      # Gemini agent assets
│   ├── kiro/                        # Kiro CLI agent + skills
│   ├── opencode/                    # OpenCode agent assets
│   └── shared/                      # Cross-tool prompts/framework
├── scripts/
│   ├── build-release.sh            # Clean dist/ and build release artifacts
│   ├── install.sh                   # Thin source-install bootstrap wrapper
│   └── install-agents.sh            # Thin compatibility wrapper
├── Justfile                         # Contributor task runner
├── docs/                            # Documentation
├── releases/                        # Per-release notes (v<version>.md)
├── pyproject.toml                   # Workspace root
└── CONTRIBUTING.md
```

## Cross-harness session export (session DB as single source of truth)

The session DB (`~/.config/studyloop/sessions.db`) is the single source of
truth for what the user is learning and struggling with, across every coding
harness (Claude Code, Kiro, Gemini, OpenCode) and StudyLoop's own study
sessions. For it to stay populated, each harness must run `session-export` at
session end. `studyloop install agents` now wires this automatically:

- **Steering mandate** — `agents/shared/session-db-mandate.md` is rendered per
  harness (substituting the right `session-export --<flag>`) into that
  harness's steering file (`~/.claude/rules/session-db.md`,
  `~/.kiro/steering/session-db.md`, etc.). Idempotent via the
  `studyloop:session-export-mandate` sentinel.
- **Claude Stop hook** — `install_claude_stop_hook()` merges a
  `session-export --claude-only` entry into the `Stop` array of
  `~/.claude/settings.json` (preserving existing hooks; idempotent).
- **Doctor check** — `studyloop doctor --category harness` warns when a
  harness is unwired; `studyloop doctor --fix` deploys the mandate + hook.

Codex is intentionally excluded (no codex source in `SOURCE_CHOICES` yet).
The wiring lives in `installers.py` (`_HARNESS_EXPORT`,
`install_session_db_mandate`, `install_claude_stop_hook`) and the doctor check
in `doctor/harness.py`.

## Spec-Driven Changes (OpenSpec)

Behaviour is specified in `openspec/`, not only in code and PR descriptions.
Full contract: [OpenSpec Framework](https://github.com/Hookey-Street-Software/StudyLoop/blob/main/docs/openspec.md)
(`docs/openspec.md` in the checkout).

- `openspec/specs/<capability>/spec.md` — the 18 capability specs describe
  behaviour that is **already shipped**, warts included. They were written by
  reading the checkout, so a spec that disagrees with the code is a bug in
  the spec.
- `openspec/changes/<change-id>/` — work in flight: `proposal.md`,
  `design.md`, `tasks.md`, plus a spec delta per affected capability.
  `openspec archive <id>` folds the deltas into `specs/` when the work lands.

Before you start a behavioural change:

```bash
openspec list --specs                          # find the owning capability
openspec show <capability> --type spec         # read its current requirements
```

Then propose the change (the `openspec-propose` skill runs these):

```bash
openspec new change "<kebab-id>"
openspec status --change "<kebab-id>"
```

Skip the ceremony for typos, dependency bumps with no behaviour delta,
test-only additions, and doc edits. Do **not** skip it when a fix changes
behaviour a requirement describes — update that requirement.

Validate before pushing:

```bash
just spec-check      # also runs inside just preflight
```

## How to Add a New Session Exporter

Session exporters live in `packages/agent-session-tools/src/agent_session_tools/exporters/`.

1. Create a new file (e.g., `mytools.py`):

```python
"""MyTool session exporter."""

import sqlite3
from pathlib import Path

from .base import ExportStats, commit_batch


class MyToolExporter:
    """Export sessions from MyTool."""

    @property
    def source_name(self) -> str:
        return "mytool"

    def is_available(self) -> bool:
        """Check if MyTool data exists on this system."""
        return Path.home().joinpath(".mytool", "history").exists()

    def export_all(
        self,
        conn: sqlite3.Connection,
        incremental: bool = True,
        batch_size: int = 50,
    ) -> ExportStats:
        """Export all sessions from MyTool."""
        stats = ExportStats()
        # Parse your tool's session files
        # Build session and message dicts
        # Call commit_batch(conn, sessions, messages, stats)
        return stats
```

2. Register it in `exporters/__init__.py`:

```python
from .mytool import MyToolExporter

EXPORTERS = {
    # ... existing exporters ...
    "mytool": MyToolExporter(),
}
```

3. Add tests in `packages/agent-session-tools/tests/`

Each exporter must implement the `SessionExporter` protocol: `source_name`, `is_available()`, and `export_all()`.

## How to Add a New Study Topic

Edit `~/.config/studyloop/config.yaml`:

```yaml
topics:
  - name: Kubernetes
    slug: kubernetes
    obsidian_path: 2-Areas/Study/Kubernetes
    tags: [kubernetes, k8s, containers, orchestration]
```

The `tags` list is used by `studyloop struggles` and `studyloop review` to match session content to topics.

If you want to add default topics that ship with the project, edit `packages/studyloop/src/studyloop/topics.py` and update the `get_topics()` function.

## How to Modify Agent Behaviour

| What to change | Where to edit |
|---------------|---------------|
| Kiro agent persona | `agents/kiro/study-mentor/persona.md` |
| Kiro session workflows | `agents/kiro/skills/study-mentor/SKILL.md` |
| Socratic questioning style | `agents/kiro/skills/audhd-socratic-mentor/SKILL.md` |
| Network→DE bridges | `agents/kiro/skills/audhd-socratic-mentor/references/network-bridges.md` |
| Progress tracking | `agents/kiro/skills/tutor-progress-tracker/SKILL.md` |
| Claude socratic-mentor | `agents/claude/socratic-mentor.md` |
| Codex project instructions | `agents/codex/AGENTS.md` |

Agent files are symlinked by the installer, so edits in the repo are immediately reflected.

## Pull Request Process

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-change`
3. Make your changes
4. Run checks:
   ```bash
   just release-check
   ```
5. Commit with a descriptive message
6. Open a PR against `main`

CI runs lint, typecheck, SAST, dependency audits, the default test suite on
Python 3.12 and 3.13, the four optional profile jobs, browser smoke, and a build
plus installed-wheel smoke on every PR.

**CI does not run the e2e journey suite.** The default `pytest` selection
deselects the `e2e` marker, so a green PR says nothing about the browser paths
under `packages/studyloop/tests/e2e/`. Run those locally before merging a UI
change — see [CI Workflows](https://github.com/Hookey-Street-Software/StudyLoop/blob/main/docs/ci.md)
for exactly what each workflow covers and what it does not.

## Documentation Style Guide

### Custom Admonitions

The docs use custom MkDocs admonition types defined in `docs/stylesheets/audhd.css`. Use these in documentation pages:

| Type | Syntax | When to Use |
|------|--------|-------------|
| `struggling` | `!!! struggling "Title"` | Anti-patterns, common mistakes, what NOT to do |
| `learning` | `!!! learning "Title"` | Key learning points, things to remember |
| `confident` | `!!! confident "Title"` | Advanced tips for when the reader is comfortable |
| `mastered` | `!!! mastered "Title"` | Expert-level insights, deep dives |
| `parking-lot` | `!!! parking-lot "Title"` | Tangential information — interesting but not essential now |
| `micro-celebration` | `!!! micro-celebration "Title"` | Positive reinforcement, progress acknowledgment |
| `energy-check` | `!!! energy-check "Title"` | Important callouts about cognitive load or energy |

These map to confidence levels and AuDHD support patterns. Standard MkDocs admonitions (`tip`, `warning`, `note`, etc.) also work.

## Code of Conduct

- Be kind and constructive
- Be inclusive — this project is built for neurodivergent learners, so respect different ways of thinking and communicating
- Be direct — clear communication is an accessibility feature, not rudeness
- No gatekeeping — all skill levels welcome
- If someone's struggling, help them learn rather than doing it for them (that's the whole point of this project)
