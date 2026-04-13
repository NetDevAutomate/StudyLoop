# Contributing

How to set up a development environment, add features, and submit changes.

## Table of Contents

- [Development Setup](#development-setup)
- [Task Runner](#task-runner)
- [Code Style](#code-style)
- [Running Tests](#running-tests)
- [Release Build](#release-build)
- [Project Structure](#project-structure)
- [How to Add a New Session Exporter](#how-to-add-a-new-session-exporter)
- [How to Add a New Study Topic](#how-to-add-a-new-study-topic)
- [How to Modify Agent Behaviour](#how-to-modify-agent-behaviour)
- [Pull Request Process](#pull-request-process)
- [Code of Conduct](#code-of-conduct)

## Development Setup

```bash
git clone https://github.com/NetDevAutomate/Socratic-Study-Mentor.git
cd socratic-study-mentor

# Install all packages with dev dependencies
uv sync --all-packages --extra dev --extra test

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

`just release-check` runs the full local release gate:
- tests
- lint
- typecheck
- strict docs build
- release artifact build

## Code Style

- **Linter/formatter**: [ruff](https://docs.astral.sh/ruff/) (configured in each `pyproject.toml`)
- **Type checker**: [pyright](https://github.com/microsoft/pyright) in basic mode
- **Line length**: 100 characters
- **Target**: Python 3.12+ (both studyctl and agent-session-tools)

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
- `packages/studyctl/tests/` — studyctl CLI and review tests
- `packages/agent-session-tools/tests/` — session tools tests

## Release Build

Use the shared release-build script for local package verification:

```bash
just build-release
```

This recipe calls `./scripts/build-release.sh`, which:
- deletes old contents from `dist/`
- builds the `studyctl` sdist and wheel with `uv build --package studyctl --no-sources`

The release workflow uses the same script, so local and CI builds follow the same path.

## Project Structure

```
socratic-study-mentor/
├── packages/
│   ├── studyctl/                    # User-facing study toolkit
│   │   ├── src/studyctl/
│   │   │   ├── adapters/           # Claude, Codex, Gemini, Kiro, OpenCode, local-LLM adapters
│   │   │   ├── cli/                # Click command surface
│   │   │   ├── content/            # NotebookLM and PDF processing
│   │   │   ├── doctor/             # Diagnostics and auto-fix checks
│   │   │   ├── history/            # Study session persistence helpers
│   │   │   ├── logic/              # Functional-core orchestration helpers
│   │   │   ├── mcp/                # studyctl MCP server/tooling
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
├── Formula/studyctl.rb              # Homebrew formula
├── docs/                            # Documentation
├── pyproject.toml                   # Workspace root
└── CONTRIBUTING.md
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

Edit `~/.config/studyctl/config.yaml`:

```yaml
topics:
  - name: Kubernetes
    slug: kubernetes
    obsidian_path: 2-Areas/Study/Kubernetes
    tags: [kubernetes, k8s, containers, orchestration]
```

The `tags` list is used by `studyctl struggles` and `studyctl review` to match session content to topics.

If you want to add default topics that ship with the project, edit `packages/studyctl/src/studyctl/topics.py` and update the `get_topics()` function.

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

CI runs lint, typecheck, and tests automatically on every PR.

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
