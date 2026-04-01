# Testing Guide

How to run, write, and maintain tests in the socratic-study-mentor workspace.

## Running Tests

The workspace has two packages with independent test suites:

| Package | Tests | Path |
|---------|-------|------|
| studyctl | 293 | `packages/studyctl/tests/` |
| agent-session-tools | 357 | `packages/agent-session-tools/tests/` |

### Prerequisites

Before running tests, install all workspace packages:

```bash
uv sync --all-packages
```

Plain `uv sync` only installs root deps — you will get `ModuleNotFoundError` on `click`, `typer`, etc. if you skip this.

### Invocation Paths

**From workspace root (recommended):**

```bash
uv run pytest                          # both packages, 650 tests
uv run pytest packages/studyctl/tests/ # studyctl only
uv run pytest packages/agent-session-tools/tests/  # agent-session-tools only
```

The root `pyproject.toml` sets `--import-mode=importlib` which is **load-bearing** — it prevents namespace conflicts between the two packages. Do not remove or override this.

**From inside a package directory:**

```bash
cd packages/studyctl
uv run pytest                          # uses studyctl's own pyproject.toml config
```

Note: when running from a member directory, the root config's `--import-mode=importlib` is NOT applied (the member's own `addopts` take precedence). This is fine for focused development but the workspace root is the authoritative invocation path.

### Useful Options

```bash
uv run pytest -x                       # stop on first failure
uv run pytest -k "test_review"         # run tests matching a pattern
uv run pytest -m "not integration"     # skip integration tests
uv run pytest --tb=long                # verbose tracebacks
uv run pytest -v                       # show individual test names
```

## Why No conftest.py in studyctl

This is the single most important architectural constraint in the test suite.

**The problem:** When pytest collects both packages from the workspace root, it loads conftest files from both `packages/agent-session-tools/tests/conftest.py` and (if it existed) `packages/studyctl/tests/conftest.py`. These conftest files register as pytest plugins via pluggy. With `--import-mode=importlib`, the two conftest modules would occupy the same plugin namespace, causing a registration conflict.

**The solution:** agent-session-tools has a conftest (it was here first and holds shared fixtures like `temp_db`, `migrated_db`, `populated_db`). studyctl does NOT have a conftest. All studyctl fixtures are either:

1. **Inlined** in each test file (the current pattern for most tests)
2. **Imported from `_helpers.py`** — a plain Python module with factory functions (not pytest fixtures)

**Never create `packages/studyctl/tests/conftest.py`.** If you need shared utilities for studyctl tests, add them to `packages/studyctl/tests/_helpers.py`.

## Fixture Patterns

### agent-session-tools: Use conftest

Shared fixtures live in `packages/agent-session-tools/tests/conftest.py`:

- `temp_db` — temporary SQLite DB with base schema, yields `(conn, db_path)`
- `migrated_db` — same as `temp_db` but with all migrations applied
- `populated_db` — `migrated_db` with a sample session and message inserted
- `temp_config_dir` — temporary config directory structure
- `sample_session_data` — dict with canonical session fields
- `sample_message_data` — dict with canonical message fields

Use these directly in your test function signatures:

```python
def test_export_creates_session(migrated_db, tmp_path):
    conn, db_path = migrated_db
    # conn has all migrations applied, ready for exporter testing
```

### studyctl: Use _helpers.py or Inline

Import factory functions from `_helpers.py` and wrap them in `@pytest.fixture`:

```python
import pytest
from _helpers import make_review_db, make_isolated_config


@pytest.fixture()
def review_db(tmp_path):
    return make_review_db(tmp_path)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    return make_isolated_config(tmp_path, monkeypatch)


def test_something(review_db):
    # review_db is a Path to a temp SQLite file with review tables
    ...
```

**Available helpers:**

| Function | Returns | What it does |
|----------|---------|--------------|
| `make_review_db(tmp_path)` | `Path` | Creates a temp SQLite DB with review schema (WAL mode) |
| `make_isolated_config(tmp_path, monkeypatch)` | `Path` | Redirects `CONFIG_DIR` and `_CONFIG_PATH` to temp dir |

For simple, one-off fixtures, just inline them in the test file. Only use `_helpers.py` when the pattern recurs across multiple files.

## Mock Conventions

Two tools, each for a specific purpose:

### `monkeypatch` — for attributes and environment

Use `monkeypatch.setattr` to replace module-level constants and object attributes. Use `monkeypatch.setenv` for environment variables. These auto-revert when the test ends.

```python
def test_custom_config_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("studyctl.settings.CONFIG_DIR", tmp_path)
    monkeypatch.setenv("STUDYCTL_CONFIG", str(tmp_path / "config.yaml"))
    # settings module now reads from tmp_path
```

### `unittest.mock.patch` — for callables

Use `patch` when you need to replace a function AND verify it was called. The `MagicMock`/`AsyncMock` objects provide `.assert_called_once_with()`, `.call_args`, etc.

```python
from unittest.mock import patch

def test_pypi_check_offline(tmp_path):
    with patch("studyctl.doctor.updates._fetch_pypi_version", return_value="2.1.0"):
        result = check_update_available()
        assert result.status == "pass"
```

For async code, use `AsyncMock`:

```python
from unittest.mock import AsyncMock, patch

@patch("studyctl.content.notebooklm_client.asyncio.sleep", new_callable=AsyncMock)
async def test_rate_limit(mock_sleep):
    await generate_with_rate_limit()
    mock_sleep.assert_called()
```

### When to use which

| Scenario | Tool |
|----------|------|
| Replace a module constant (`CONFIG_DIR`, `DEFAULT_DB`) | `monkeypatch.setattr` |
| Set/override an env var | `monkeypatch.setenv` |
| Replace a function to control its return value | `patch` (context manager) |
| Replace a function AND verify call arguments | `patch` (decorator or context manager) |
| Replace an async function | `patch` with `new_callable=AsyncMock` |
| Replace `shutil.which` for tool detection | `patch` |
| Replace `subprocess.run` for command isolation | `patch` |

## Test Markers

### `@pytest.mark.integration`

For tests that require external infrastructure (tmux, network, real databases). These are excluded from fast local runs:

```python
import pytest

pytestmark = pytest.mark.integration  # marks entire module

# Or per-test:
@pytest.mark.integration
def test_tmux_session_lifecycle():
    ...
```

Run integration tests explicitly:

```bash
uv run pytest -m integration           # only integration tests
uv run pytest -m "not integration"     # skip integration tests
```

### `pytest.importorskip` — for optional dependencies

Tests that require optional packages use `importorskip` at module level. The test file is collected normally but all tests in it are **skipped** at runtime if the dependency is missing:

```python
# At the top of the file, before any other imports from the optional package:
pytest.importorskip("pymupdf")
pytest.importorskip("fastapi")
```

Currently skipped groups: `pymupdf` (content splitter), `notebooklm` (notebooklm client), `fastapi` (web app/artefacts), `mcp` (MCP tools).

## Adding a New Test

### For studyctl

1. Create `packages/studyctl/tests/test_<module>.py`
2. Import helpers if needed: `from _helpers import make_review_db`
3. Define fixtures inline or wrap helpers in `@pytest.fixture`
4. If testing optional-dep code, add `pytest.importorskip("package")` at module level
5. Do NOT create a conftest.py

### For agent-session-tools

1. Create `packages/agent-session-tools/tests/test_<module>.py`
2. Use conftest fixtures (`temp_db`, `migrated_db`, etc.) directly in test signatures
3. For exporter tests, use `migrated_db` — it has all migrations applied
4. Add new shared fixtures to conftest.py if they'll be used by 3+ test files

### Naming

- Test files: `test_<module_name>.py`
- Test classes: `Test<Feature>` (optional — flat functions are fine)
- Test functions: `test_<behaviour_under_test>`
- Fixtures: descriptive nouns (`review_db`, `isolated_config`, `projects_dir`)

## Known TODOs

- **Coverage configuration** — `pytest-cov` is in dev deps but studyctl has no `[tool.coverage.run]` config. Agent-session-tools does.
- **`addopts` split** — running from workspace root uses `--import-mode=importlib` only. Running from a member directory uses that member's `addopts`. The root path is authoritative.
- **Worktree tests** — 8 test files in `.claude/worktrees/feat+live-session-dashboard/` need merging (blocked on 5 source modules landing in main first).
