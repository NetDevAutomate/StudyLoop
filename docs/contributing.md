# Contributing

How to set up a development environment, add features, and submit changes.

---

## Development Setup

```bash
git clone <your-repo-url>/socratic-study-mentor.git
cd socratic-study-mentor

# Install all packages with dev dependencies
uv sync --all-packages --extra dev --extra test

# Install pre-commit hooks
uv run pre-commit install
```

Pre-commit runs: `ruff` (lint/format), `trailing-whitespace`, `end-of-file-fixer`, `detect-secrets`, `detect-private-key`, `detect-aws-credentials`.

---

## Code Style

- **Linter/formatter**: ruff (configured in each `pyproject.toml`)
- **Type checker**: pyright in basic mode
- **Line length**: 100 characters
- **Target**: Python 3.10+ (agent-session-tools), Python 3.12+ (studyctl)

```bash
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run pyright packages/         # Type check
```

Key conventions: type hints on all public functions, docstrings on public APIs, no bare `except:`, no mutable default arguments, use `Path` objects.

---

## Running Tests

```bash
uv run pytest                    # All tests
uv run pytest -v                 # Verbose
uv run pytest -k "test_search"   # Pattern match
```

---

## Adding a New Session Exporter

Create a file in `packages/agent-session-tools/src/agent_session_tools/exporters/`:

```python
class MyToolExporter:
    @property
    def source_name(self) -> str:
        return "mytool"

    def is_available(self) -> bool:
        return Path.home().joinpath(".mytool", "history").exists()

    def export_all(self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50) -> ExportStats:
        stats = ExportStats()
        # Parse sessions, call commit_batch(conn, sessions, messages, stats)
        return stats
```

Register in `exporters/__init__.py` and add tests.

---

## Adding a New Study Topic

Edit `~/.config/studyctl/config.yaml`:

```yaml
topics:
  - name: Kubernetes
    slug: kubernetes
    obsidian_path: 2-Areas/Study/Kubernetes
    tags: [kubernetes, k8s, containers, orchestration]
```

---

## Pull Request Process

1. Fork → feature branch → make changes
2. Run: `uv run ruff check . && uv run pyright packages/ && uv run pytest`
3. Open PR against `main`

CI runs lint, typecheck, and tests automatically.
