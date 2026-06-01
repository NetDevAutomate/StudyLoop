# StudyLoop Next Quality Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the next five repo-quality improvements: profile-specific CI, `studyloop self-test`, web route service extraction, browser smoke coverage, and release/version consistency automation.

**Architecture:** Keep the work as five independently shippable slices. CI/profile and release checks live in workflow/scripts/Justfile surfaces; self-test lives in a small CLI command backed by a testable pure-Python module; route service extraction moves business decisions out of FastAPI handlers without changing URLs; browser smoke tests reuse the existing Playwright fixtures.

**Tech Stack:** Python 3.12/3.13, Click, pytest, pytest-playwright, FastAPI, uv, Just, GitHub Actions, MkDocs.

---

## Execution Workflows

### Recommended Subagent Workflow

Use one fresh worker per task group, then integrate centrally.

1. **Worker A — CI Profiles**
   - Owns `.github/workflows/ci.yml`, `Justfile`, `pyproject.toml`, `packages/studyloop/pyproject.toml`.
   - Does not edit CLI, web routes, or docs except workflow docs explicitly listed in Task 1.
   - Verification: `just --list`, `just --dry-run test-web`, `just --dry-run test-content`, `just --dry-run test-semantic`, YAML parse.

2. **Worker B — Self-Test**
   - Owns `packages/studyloop/src/studyloop/self_test.py`, `packages/studyloop/src/studyloop/cli/_self_test.py`, CLI registration, self-test docs, and self-test tests.
   - Does not edit doctor internals except importing shared types if needed.
   - Verification: self-test unit tests and `uv run --group dev studyloop self-test --json`.

3. **Worker C — Web Services**
   - Owns new `packages/studyloop/src/studyloop/web/services/` modules and the narrow route edits needed to delegate to them.
   - Does not change route URLs, response bodies, or WebSocket frame shapes.
   - Verification: route/service unit tests, web session/content focused tests.

4. **Worker D — Browser Smoke**
   - Owns Playwright smoke test file and the CI job that runs it.
   - Does not modify production UI unless a failing smoke test proves a real defect.
   - Verification: new smoke test locally with `pytest -m e2e`.

5. **Worker E — Release Consistency**
   - Owns `scripts/check-release-consistency.py`, `Justfile`, CI release job wiring, release docs, and tests for the script.
   - Does not bump versions.
   - Verification: script tests and `just release-consistency`.

Central integrator then runs:

```bash
just lint
just typecheck
just test
just docs
just audit
just audit-full
just smoke-installed
```

### Commit Workflow

Use these commit boundaries:

```text
ci: add optional profile test jobs
feat(cli): add self-test command
refactor(web): extract route services
test(web): add browser smoke coverage
chore(release): verify version and release consistency
docs: document quality workflows
```

Do not combine route service extraction with browser smoke unless the smoke tests reveal a production bug that must be fixed in the same commit.

### Failure Workflow

If a task fails twice on the same issue:

1. Capture the exact command and failing output.
2. Reduce the failing surface to the smallest test or import.
3. Check whether the failure belongs to the current task ownership.
4. If it crosses ownership, stop and report the cross-task dependency before editing outside scope.

---

## File Structure

### CI/Profile Files

- Modify: `.github/workflows/ci.yml`
  - Add `web-profile`, `content-profile`, `semantic-profile`, and `browser-smoke` jobs.
  - Keep `audit-full` explicit and optional-surface aware.
- Modify: `Justfile`
  - Add local recipes matching CI profile jobs.
- Modify: `pyproject.toml`
  - Add profile markers if needed: `web`, `content`, `semantic`, `browser_smoke`.
- Modify: `packages/studyloop/pyproject.toml`
  - Keep package-local marker declarations aligned if package-local test execution is still supported.

### Self-Test Files

- Create: `packages/studyloop/src/studyloop/self_test.py`
  - Pure functions that run lightweight checks and return structured results.
- Create: `packages/studyloop/src/studyloop/cli/_self_test.py`
  - Click command wrapper.
- Modify: `packages/studyloop/src/studyloop/cli/__init__.py`
  - Register lazy command `self-test`.
- Create: `packages/studyloop/tests/test_self_test.py`
  - Unit tests for check aggregation, JSON shape, exit code logic, and CLI rendering.
- Modify: `docs/cli-reference.md`
  - Add `studyloop self-test`.
- Modify: `docs/setup-guide.md`
  - Add post-install self-test guidance.

### Web Service Files

- Create: `packages/studyloop/src/studyloop/web/services/__init__.py`
- Create: `packages/studyloop/src/studyloop/web/services/content_generation.py`
  - Request planning, provider availability calculation, and job queue helpers.
- Create: `packages/studyloop/src/studyloop/web/services/session_start.py`
  - Agent resolution, topic resolution, session state payload building, and transport factory selection.
- Modify: `packages/studyloop/src/studyloop/web/routes/content_gen/_catalog.py`
- Modify: `packages/studyloop/src/studyloop/web/routes/content_gen/_jobs.py`
- Modify: `packages/studyloop/src/studyloop/web/routes/session/_start.py`
- Create: `packages/studyloop/tests/test_web_content_generation_service.py`
- Create: `packages/studyloop/tests/test_web_session_start_service.py`

### Browser Smoke Files

- Create: `packages/studyloop/tests/test_web_smoke_browser.py`
  - Fast Playwright checks for initial load, nav, provider panel, session form, and protected LAN mode.
- Modify: `.github/workflows/ci.yml`
  - Add browser smoke job.
- Modify: `Justfile`
  - Add `test-browser-smoke`.

### Release Consistency Files

- Create: `scripts/check-release-consistency.py`
  - Validates package version, root package version, release note file, docs references, wheel metadata after build.
- Create: `packages/studyloop/tests/test_release_consistency_script.py`
  - Unit tests using a temporary repo tree and subprocess invocation.
- Modify: `Justfile`
  - Add `release-consistency` and include it in `release-check`.
- Modify: `.github/workflows/ci.yml`
  - Run release consistency before or after `build`.
- Modify: `docs/release-process.md`
  - Add the consistency gate.

---

## Task 1: Add Profile-Specific CI Jobs

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `Justfile`
- Modify: `pyproject.toml`
- Modify: `packages/studyloop/pyproject.toml`

- [ ] **Step 1: Add profile recipes to `Justfile`**

Add these recipes after `test:`:

```just
test-web:
    uv run --group dev pytest \
      packages/studyloop/tests/test_web_app.py \
      packages/studyloop/tests/test_web_content_gen_rest.py \
      packages/studyloop/tests/test_web_content_gen_ws.py \
      packages/studyloop/tests/test_web_content_providers.py \
      packages/studyloop/tests/test_web_secrets_route.py \
      packages/studyloop/tests/test_web_session_start_acp.py \
      packages/studyloop/tests/test_web_session_start_pty.py \
      packages/studyloop/tests/test_web_session_ws.py \
      packages/studyloop/tests/test_web_runtime_feedback.py \
      -q

test-content:
    uv run --group dev pytest \
      packages/studyloop/tests/test_content_cli.py \
      packages/studyloop/tests/test_content_generators.py \
      packages/studyloop/tests/test_content_generators_runner.py \
      packages/studyloop/tests/test_content_generators_stub.py \
      packages/studyloop/tests/test_content_job_runner.py \
      packages/studyloop/tests/test_content_scope.py \
      packages/studyloop/tests/test_content_storage.py \
      packages/studyloop/tests/test_content_storage_merge.py \
      packages/studyloop/tests/test_content_workflow.py \
      -q

test-semantic:
    uv run --group dev pytest \
      packages/agent-session-tools/tests/test_embeddings.py \
      packages/agent-session-tools/tests/test_semantic_search.py \
      -q
```

- [ ] **Step 2: Run recipe discovery**

Run:

```bash
just --list
```

Expected:

```text
Available recipes:
    test-web
    test-content
    test-semantic
```

- [ ] **Step 3: Add CI jobs**

In `.github/workflows/ci.yml`, add jobs after `test:`:

```yaml
  web-profile:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      - uses: astral-sh/setup-uv@e4db8464a088ece1b920f60402e813ea4de65b8f # v4
        with:
          python-version: "3.12"
      - run: uv sync --all-packages --group dev --extra web
      - run: just test-web

  content-profile:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      - uses: astral-sh/setup-uv@e4db8464a088ece1b920f60402e813ea4de65b8f # v4
        with:
          python-version: "3.12"
      - run: uv sync --all-packages --group dev --extra content
      - run: just test-content

  semantic-profile:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      - uses: astral-sh/setup-uv@e4db8464a088ece1b920f60402e813ea4de65b8f # v4
        with:
          python-version: "3.12"
      - run: uv sync --all-packages --group dev --extra semantic
      - run: just test-semantic
```

- [ ] **Step 4: Validate workflow YAML**

Run:

```bash
python - <<'PY'
from pathlib import Path
import yaml
data = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
jobs = data["jobs"]
for name in ["web-profile", "content-profile", "semantic-profile"]:
    assert name in jobs, name
print("ci workflow parsed")
PY
```

Expected:

```text
ci workflow parsed
```

- [ ] **Step 5: Run the local profile tests**

Run:

```bash
just test-web
just test-content
just test-semantic
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml Justfile pyproject.toml packages/studyloop/pyproject.toml
git commit -m "ci: add optional profile test jobs"
```

---

## Task 2: Add `studyloop self-test`

**Files:**
- Create: `packages/studyloop/src/studyloop/self_test.py`
- Create: `packages/studyloop/src/studyloop/cli/_self_test.py`
- Modify: `packages/studyloop/src/studyloop/cli/__init__.py`
- Create: `packages/studyloop/tests/test_self_test.py`
- Modify: `docs/cli-reference.md`
- Modify: `docs/setup-guide.md`

- [ ] **Step 1: Write failing self-test unit tests**

Create `packages/studyloop/tests/test_self_test.py`:

```python
"""Tests for the lightweight post-install self-test command."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from studyloop.self_test import SelfTestResult, exit_code_for, run_self_tests


def test_exit_code_for_success_warn_and_fail() -> None:
    assert exit_code_for([SelfTestResult("cli", "pass", "ok")]) == 0
    assert exit_code_for([SelfTestResult("cli", "warn", "check config")]) == 1
    assert exit_code_for([SelfTestResult("cli", "fail", "missing command")]) == 2


def test_run_self_tests_returns_core_check_names() -> None:
    results = run_self_tests()
    names = {result.name for result in results}
    assert {"cli_import", "config_read", "database_path", "web_import"}.issubset(names)


def test_self_test_json_output() -> None:
    from studyloop.cli._self_test import self_test

    runner = CliRunner()
    fake = [SelfTestResult("cli_import", "pass", "studyloop imports")]
    with patch("studyloop.cli._self_test.run_self_tests", return_value=fake):
        result = runner.invoke(self_test, ["--json"], catch_exceptions=False)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == [{"name": "cli_import", "status": "pass", "message": "studyloop imports"}]


def test_self_test_quiet_output() -> None:
    from studyloop.cli._self_test import self_test

    runner = CliRunner()
    fake = [SelfTestResult("cli_import", "pass", "studyloop imports")]
    with patch("studyloop.cli._self_test.run_self_tests", return_value=fake):
        result = runner.invoke(self_test, ["--quiet"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "1 passed" in result.output
    assert "cli_import" not in result.output
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_self_test.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'studyloop.self_test'
```

- [ ] **Step 3: Add self-test core module**

Create `packages/studyloop/src/studyloop/self_test.py`:

```python
"""Lightweight post-install self-tests for StudyLoop."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

SelfTestStatus = Literal["pass", "warn", "fail"]


@dataclass(frozen=True, slots=True)
class SelfTestResult:
    name: str
    status: SelfTestStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _check_cli_import() -> SelfTestResult:
    try:
        from studyloop.cli import cli

        command_count = len(getattr(cli, "lazy_subcommands", {}) or {})
        return SelfTestResult("cli_import", "pass", f"studyloop CLI imports ({command_count} commands)")
    except Exception as exc:
        return SelfTestResult("cli_import", "fail", f"studyloop CLI import failed: {exc!r}")


def _check_config_read() -> SelfTestResult:
    try:
        from studyloop.settings import get_config_path, load_settings

        settings = load_settings()
        return SelfTestResult("config_read", "pass", f"config readable at {get_config_path()}; base={settings.content.base_path}")
    except FileNotFoundError as exc:
        return SelfTestResult("config_read", "warn", f"config not created yet: {exc}")
    except Exception as exc:
        return SelfTestResult("config_read", "fail", f"config read failed: {exc!r}")


def _check_database_path() -> SelfTestResult:
    try:
        from studyloop.paths import data_dir

        db_path = data_dir() / "review.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("SELECT 1").fetchone()
        return SelfTestResult("database_path", "pass", f"database directory writable: {db_path.parent}")
    except Exception as exc:
        return SelfTestResult("database_path", "fail", f"database check failed: {exc!r}")


def _check_web_import() -> SelfTestResult:
    try:
        from studyloop.web.app import create_app

        create_app(study_dirs=[])
        return SelfTestResult("web_import", "pass", "web app imports and creates")
    except ImportError as exc:
        return SelfTestResult("web_import", "warn", f"web extra not installed: {exc}")
    except Exception as exc:
        return SelfTestResult("web_import", "fail", f"web app creation failed: {exc!r}")


def run_self_tests() -> list[SelfTestResult]:
    """Run quick local checks that are safe immediately after installation."""
    return [_check_cli_import(), _check_config_read(), _check_database_path(), _check_web_import()]


def exit_code_for(results: list[SelfTestResult]) -> int:
    if any(result.status == "fail" for result in results):
        return 2
    if any(result.status == "warn" for result in results):
        return 1
    return 0


def results_as_json(results: list[SelfTestResult]) -> str:
    return json.dumps([result.to_dict() for result in results], indent=2)
```

- [ ] **Step 4: Add Click command**

Create `packages/studyloop/src/studyloop/cli/_self_test.py`:

```python
"""studyloop self-test — lightweight post-install verification."""

from __future__ import annotations

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.self_test import exit_code_for, results_as_json, run_self_tests


def _summary(results) -> str:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for result in results:
        counts[result.status] += 1
    return f"{counts['pass']} passed, {counts['warn']} warnings, {counts['fail']} failures"


@click.command("self-test")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--quiet", is_flag=True, help="Print only the summary line.")
def self_test(as_json: bool, quiet: bool) -> None:
    """Run lightweight post-install checks."""
    results = run_self_tests()
    exit_code = exit_code_for(results)

    if as_json:
        click.echo(results_as_json(results))
        raise click.exceptions.Exit(exit_code)

    if quiet:
        click.echo(_summary(results))
        raise click.exceptions.Exit(exit_code)

    table = Table(title="StudyLoop Self-Test")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Message")
    for result in results:
        table.add_row(result.name, result.status, result.message)
    console.print(table)
    console.print(_summary(results))
    raise click.exceptions.Exit(exit_code)
```

- [ ] **Step 5: Register lazy command**

Modify `packages/studyloop/src/studyloop/cli/__init__.py`:

```python
# _self_test.py — lightweight post-install verification
"self-test": "studyloop.cli._self_test:self_test",
```

Place it near `"doctor"` so health-related commands are grouped in the lazy map.

- [ ] **Step 6: Run self-test tests**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_self_test.py packages/studyloop/tests/test_cli_docs.py -q
```

Expected:

```text
passed
```

- [ ] **Step 7: Add documentation**

In `docs/cli-reference.md`, add:

```bash
studyloop self-test                       # Lightweight post-install verification
studyloop self-test --json                # Machine-readable self-test results
```

In `docs/setup-guide.md`, add this after install:

```bash
studyloop self-test
studyloop doctor
```

- [ ] **Step 8: Commit**

```bash
git add packages/studyloop/src/studyloop/self_test.py \
  packages/studyloop/src/studyloop/cli/_self_test.py \
  packages/studyloop/src/studyloop/cli/__init__.py \
  packages/studyloop/tests/test_self_test.py \
  docs/cli-reference.md docs/setup-guide.md
git commit -m "feat(cli): add self-test command"
```

---

## Task 3: Extract Web Route Business Logic Into Services

**Files:**
- Create: `packages/studyloop/src/studyloop/web/services/__init__.py`
- Create: `packages/studyloop/src/studyloop/web/services/content_generation.py`
- Create: `packages/studyloop/src/studyloop/web/services/session_start.py`
- Modify: `packages/studyloop/src/studyloop/web/routes/content_gen/_catalog.py`
- Modify: `packages/studyloop/src/studyloop/web/routes/content_gen/_jobs.py`
- Modify: `packages/studyloop/src/studyloop/web/routes/session/_start.py`
- Create: `packages/studyloop/tests/test_web_content_generation_service.py`
- Create: `packages/studyloop/tests/test_web_session_start_service.py`

- [ ] **Step 1: Write content-generation service tests**

Create `packages/studyloop/tests/test_web_content_generation_service.py`:

```python
"""Tests for content-generation service helpers."""

from __future__ import annotations

from studyloop.web.services.content_generation import (
    ProviderAvailabilityInput,
    provider_is_available,
    queue_terminal_frame,
)


def test_provider_is_available_for_key_provider_with_stored_key() -> None:
    data = ProviderAvailabilityInput(
        slug="openai",
        auth_env="OPENAI_API_KEY",
        env_value="",
        stored_secret="sk-stored",
        bedrock_credentials=False,
        ollama_reachable=False,
    )
    assert provider_is_available(data) is True


def test_provider_is_unavailable_without_key_or_env() -> None:
    data = ProviderAvailabilityInput(
        slug="openai",
        auth_env="OPENAI_API_KEY",
        env_value="",
        stored_secret=None,
        bedrock_credentials=False,
        ollama_reachable=False,
    )
    assert provider_is_available(data) is False


def test_bedrock_available_with_credentials() -> None:
    data = ProviderAvailabilityInput(
        slug="bedrock",
        auth_env="AWS_BEARER_TOKEN_BEDROCK",
        env_value="",
        stored_secret=None,
        bedrock_credentials=True,
        ollama_reachable=False,
    )
    assert provider_is_available(data) is True


def test_queue_terminal_frame_drops_oldest_when_full() -> None:
    queue = [{"type": "progress", "n": 1}, {"type": "progress", "n": 2}]
    queue_terminal_frame(queue, {"type": "all_done"}, max_size=2)
    assert queue == [{"type": "progress", "n": 2}, {"type": "all_done"}]
```

- [ ] **Step 2: Run content-generation service tests to verify failure**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_web_content_generation_service.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'studyloop.web.services'
```

- [ ] **Step 3: Add content-generation service**

Create `packages/studyloop/src/studyloop/web/services/__init__.py`:

```python
"""Service helpers for web routes."""
```

Create `packages/studyloop/src/studyloop/web/services/content_generation.py`:

```python
"""Business helpers for content-generation routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderAvailabilityInput:
    slug: str
    auth_env: str
    env_value: str
    stored_secret: str | None
    bedrock_credentials: bool
    ollama_reachable: bool


def provider_is_available(data: ProviderAvailabilityInput) -> bool:
    if data.slug == "bedrock":
        return bool(data.stored_secret or data.bedrock_credentials)
    if data.slug == "ollama":
        return data.ollama_reachable
    return bool((data.stored_secret or "").strip() or data.env_value.strip())


def queue_terminal_frame(
    queue: list[dict[str, Any]], frame: dict[str, Any], *, max_size: int
) -> None:
    if len(queue) >= max_size:
        del queue[0]
    queue.append(frame)
```

- [ ] **Step 4: Write session-start service tests**

Create `packages/studyloop/tests/test_web_session_start_service.py`:

```python
"""Tests for session-start service helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from studyloop.web.services.session_start import build_session_state_payload, session_dir_name


def test_session_dir_name_is_short_and_stable() -> None:
    assert session_dir_name("Python Decorators", "abc123456789") == "pty-python-decorators-abc12345"


def test_build_session_state_payload_has_transport_and_timestamps() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    payload = build_session_state_payload(
        study_id="study-1",
        topic="Python",
        energy=6,
        energy_label="medium",
        agent="codex",
        persona_file="/tmp/persona.md",
        session_dir="/tmp/session",
        persona_hash="abcdef",
        transport="pty",
        now=now,
    )
    assert payload["study_session_id"] == "study-1"
    assert payload["transport"] == "pty"
    assert payload["started_at"] == "2026-06-01T12:00:00+00:00"
    assert payload["start_time"] == payload["started_at"]
```

- [ ] **Step 5: Add session-start service**

Create `packages/studyloop/src/studyloop/web/services/session_start.py`:

```python
"""Business helpers for web session-start routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

TransportName = Literal["pty", "acp", "ttyd"]


def session_dir_name(topic: str, study_id: str, *, prefix: str = "pty") -> str:
    slug = topic.lower().replace(" ", "-")[:20]
    return f"{prefix}-{slug}-{study_id[:8]}"


def build_session_state_payload(
    *,
    study_id: str,
    topic: str,
    energy: int,
    energy_label: str,
    agent: str,
    persona_file: str,
    session_dir: str,
    persona_hash: str,
    transport: TransportName,
    now: datetime,
) -> dict[str, object]:
    timestamp = now.isoformat()
    return {
        "study_session_id": study_id,
        "topic": topic,
        "energy": energy,
        "energy_label": energy_label,
        "mode": "focus",
        "timer_mode": "energy",
        "started_at": timestamp,
        "start_time": timestamp,
        "paused_at": None,
        "total_paused_seconds": 0,
        "persona_file": persona_file,
        "session_dir": session_dir,
        "agent": agent,
        "persona_hash": persona_hash,
        "transport": transport,
    }
```

- [ ] **Step 6: Delegate route code to services**

In `packages/studyloop/src/studyloop/web/routes/session/_start.py`, replace repeated session-dir and state payload construction with:

```python
from studyloop.web.services.session_start import build_session_state_payload, session_dir_name
```

Use:

```python
session_dir = SESSION_DIR / "sessions" / session_dir_name(body.topic, study_id)
payload = build_session_state_payload(
    study_id=study_id,
    topic=body.topic,
    energy=body.energy,
    energy_label=energy_label,
    agent=agent,
    persona_file=str(persona_file),
    session_dir=str(session_dir),
    persona_hash=persona_hash,
    transport="pty",
    now=datetime.now(UTC),
)
write_session_state(payload)
```

In `packages/studyloop/src/studyloop/web/routes/content_gen/_catalog.py`, replace availability branching with `ProviderAvailabilityInput` and `provider_is_available`.

- [ ] **Step 7: Run service and route tests**

Run:

```bash
uv run --group dev pytest \
  packages/studyloop/tests/test_web_content_generation_service.py \
  packages/studyloop/tests/test_web_session_start_service.py \
  packages/studyloop/tests/test_web_content_providers.py \
  packages/studyloop/tests/test_web_session_start_pty.py \
  packages/studyloop/tests/test_web_session_start_acp.py \
  -q
```

Expected:

```text
passed
```

- [ ] **Step 8: Commit**

```bash
git add packages/studyloop/src/studyloop/web/services \
  packages/studyloop/src/studyloop/web/routes/content_gen/_catalog.py \
  packages/studyloop/src/studyloop/web/routes/content_gen/_jobs.py \
  packages/studyloop/src/studyloop/web/routes/session/_start.py \
  packages/studyloop/tests/test_web_content_generation_service.py \
  packages/studyloop/tests/test_web_session_start_service.py
git commit -m "refactor(web): extract route services"
```

---

## Task 4: Add Browser-Level Smoke Coverage

**Files:**
- Create: `packages/studyloop/tests/test_web_smoke_browser.py`
- Modify: `Justfile`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Write browser smoke tests**

Create `packages/studyloop/tests/test_web_smoke_browser.py`:

```python
"""Browser smoke tests for the StudyLoop web UI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import (  # noqa: E402
    auth_context_fixture_factory,
    web_page_fixture_factory,
    web_server_fixture_factory,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18590

web_server = web_server_fixture_factory(WEB_PORT)
auth_context = auth_context_fixture_factory()
web_page = web_page_fixture_factory("web_server", "auth_context")


def _goto(page: Page, hash_: str = "") -> None:
    url = f"http://127.0.0.1:{WEB_PORT}/"
    if hash_:
        url += f"#{hash_}"
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)


def test_web_app_loads_flashcards_view(web_page: Page) -> None:
    _goto(web_page)
    current = web_page.evaluate("() => window.Alpine.store('nav').current")
    assert current == "flashcards"


def test_provider_panel_renders(web_page: Page) -> None:
    _goto(web_page, "generate")
    assert web_page.locator("text=Provider").first.is_visible(timeout=5000)


def test_session_start_form_renders(web_page: Page) -> None:
    _goto(web_page, "study-session")
    assert web_page.locator("text=Study Session").first.is_visible(timeout=5000)
    assert web_page.locator("input, textarea").first.is_visible(timeout=5000)


def test_navigation_to_quizzes_is_usable(web_page: Page) -> None:
    _goto(web_page)
    web_page.click('.sidebar-btn:has-text("Quizzes")')
    web_page.wait_for_function(
        "() => window.Alpine.store('nav').current === 'quizzes'",
        timeout=3000,
    )
```

- [ ] **Step 2: Add local browser smoke recipe**

In `Justfile`, add:

```just
test-browser-smoke:
    uv run --group dev pytest packages/studyloop/tests/test_web_smoke_browser.py -q
```

- [ ] **Step 3: Add CI browser smoke job**

In `.github/workflows/ci.yml`, add:

```yaml
  browser-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      - uses: astral-sh/setup-uv@e4db8464a088ece1b920f60402e813ea4de65b8f # v4
        with:
          python-version: "3.12"
      - run: uv sync --all-packages --group dev --extra web
      - run: uv run playwright install --with-deps chromium
      - run: just test-browser-smoke
```

- [ ] **Step 4: Run browser smoke locally**

Run:

```bash
uv run playwright install chromium
just test-browser-smoke
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add packages/studyloop/tests/test_web_smoke_browser.py Justfile .github/workflows/ci.yml
git commit -m "test(web): add browser smoke coverage"
```

---

## Task 5: Add Release and Version Consistency Automation

**Files:**
- Create: `scripts/check-release-consistency.py`
- Create: `packages/studyloop/tests/test_release_consistency_script.py`
- Modify: `Justfile`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/release-process.md`

- [ ] **Step 1: Write tests for the release consistency script**

Create `packages/studyloop/tests/test_release_consistency_script.py`:

```python
"""Tests for scripts/check-release-consistency.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _write_minimal_repo(root: Path, version: str = "2.5.0") -> None:
    (root / "packages/studyloop").mkdir(parents=True)
    (root / "releases").mkdir()
    (root / "dist").mkdir()
    (root / "packages/studyloop/pyproject.toml").write_text(
        f'[project]\nname = "studyloop"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "releases" / f"v{version}.md").write_text(f"# v{version}\n", encoding="utf-8")


def test_release_consistency_passes_for_matching_version(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    script = Path(__file__).resolve().parents[3] / "scripts/check-release-consistency.py"

    result = subprocess.run(
        [sys.executable, str(script), "--repo-root", str(repo), "--skip-wheel"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "release consistency passed" in result.stdout


def test_release_consistency_fails_when_release_note_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo)
    (repo / "releases/v2.5.0.md").unlink()
    script = Path(__file__).resolve().parents[3] / "scripts/check-release-consistency.py"

    result = subprocess.run(
        [sys.executable, str(script), "--repo-root", str(repo), "--skip-wheel"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "missing release notes" in result.stdout
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_release_consistency_script.py -q
```

Expected:

```text
can't open file
```

- [ ] **Step 3: Add release consistency script**

Create `scripts/check-release-consistency.py`:

```python
#!/usr/bin/env python3
"""Validate StudyLoop release metadata before packaging."""

from __future__ import annotations

import argparse
import sys
import tomllib
import zipfile
from pathlib import Path


def _version(repo_root: Path) -> str:
    data = tomllib.loads((repo_root / "packages/studyloop/pyproject.toml").read_text())
    return str(data["project"]["version"])


def _wheel_version(repo_root: Path, version: str) -> bool:
    wheels = sorted((repo_root / "dist").glob("studyloop-*.whl"))
    if not wheels:
        return False
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as zf:
            metadata_names = [name for name in zf.namelist() if name.endswith("METADATA")]
            for name in metadata_names:
                text = zf.read(name).decode("utf-8", errors="replace")
                if f"Version: {version}\n" in text:
                    return True
    return False


def check(repo_root: Path, *, skip_wheel: bool) -> list[str]:
    errors: list[str] = []
    version = _version(repo_root)
    release_note = repo_root / "releases" / f"v{version}.md"
    if not release_note.exists():
        errors.append(f"missing release notes: {release_note}")
    if not skip_wheel and not _wheel_version(repo_root, version):
        errors.append(f"no built wheel metadata found for version {version}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--skip-wheel", action="store_true")
    args = parser.parse_args(argv)

    errors = check(args.repo_root.resolve(), skip_wheel=args.skip_wheel)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("release consistency passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Make script executable**

Run:

```bash
chmod +x scripts/check-release-consistency.py
```

- [ ] **Step 5: Wire Justfile and CI**

In `Justfile`, add:

```just
release-consistency:
    uv run python scripts/check-release-consistency.py --skip-wheel
```

Change:

```just
release-check: test lint typecheck docs audit audit-full smoke-installed
```

to:

```just
release-check: test lint typecheck docs audit audit-full release-consistency smoke-installed
```

In `.github/workflows/ci.yml`, add this to the `build` job after `./scripts/build-release.sh`:

```yaml
      - run: uv run python scripts/check-release-consistency.py
```

- [ ] **Step 6: Run release consistency checks**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_release_consistency_script.py -q
just release-consistency
./scripts/build-release.sh
uv run python scripts/check-release-consistency.py
```

Expected:

```text
passed
release consistency passed
Successfully built
release consistency passed
```

- [ ] **Step 7: Commit**

```bash
git add scripts/check-release-consistency.py \
  packages/studyloop/tests/test_release_consistency_script.py \
  Justfile .github/workflows/ci.yml docs/release-process.md
git commit -m "chore(release): verify version and release consistency"
```

---

## Task 6: Document the New Quality Workflows

**Files:**
- Modify: `docs/release-process.md`
- Create or modify: `docs/troubleshooting.md`
- Modify: `mkdocs.yml`
- Modify: `README.md`

- [ ] **Step 1: Add troubleshooting page**

Create `docs/troubleshooting.md`:

````markdown
# Troubleshooting

## Install Checks

Run:

```bash
studyloop self-test
studyloop doctor
```

Use `studyloop self-test --json` when opening an issue or sharing diagnostics.

## uv Environment Drift

Run:

```bash
just sync-dev
just lint
just typecheck
```

Use `just sync-full` only when validating optional extras.

## Web And LAN Access

For local-only use:

```bash
studyloop web
```

For LAN use:

```bash
studyloop web --lan
```

Configured LAN passwords are not printed. Generated one-time passwords are printed once.

## Provider Credentials

Use the web Settings panel or environment variables for provider keys. Raw provider keys must never appear in logs, screenshots, or issue reports.
````

- [ ] **Step 2: Add nav entry**

In `mkdocs.yml`, add:

```yaml
  - Troubleshooting: troubleshooting.md
```

Place it next to Setup Guide and Release Process.

- [ ] **Step 3: Update README**

Add this to the setup section:

```markdown
For post-install diagnostics, run `studyloop self-test` first, then `studyloop doctor` for deeper environment checks.
```

- [ ] **Step 4: Run docs build**

Run:

```bash
uv run --extra docs mkdocs build --strict
```

Expected:

```text
Documentation built
```

- [ ] **Step 5: Commit**

```bash
git add docs/troubleshooting.md docs/release-process.md mkdocs.yml README.md
git commit -m "docs: document quality workflows"
```

---

## Final Verification

Run these commands after all tasks land:

```bash
just sync-dev
just lint
just typecheck
just test
just test-web
just test-content
just docs
just audit
just audit-full
just smoke-installed
```

Run these when optional browser dependencies are available:

```bash
uv run playwright install chromium
just test-browser-smoke
```

Run this when full optional semantic dependencies are installed:

```bash
just sync-semantic
just test-semantic
```

Expected final state:

```text
git status --short
```

prints no tracked or untracked project changes.

---

## Plan Self-Review

Spec coverage:

- Profile-specific CI jobs: Task 1.
- `studyloop self-test`: Task 2.
- Route business logic moved into services: Task 3.
- Browser-level smoke coverage: Task 4.
- Release/version consistency automation: Task 5.
- Workflows for execution, commits, failure handling, and verification: Execution Workflows plus Final Verification.

Placeholder scan:

- The plan contains no open-ended implementation placeholders.
- All new files have concrete initial code or exact command snippets.

Type consistency:

- `SelfTestResult`, `run_self_tests`, `exit_code_for`, and `results_as_json` are defined before CLI code uses them.
- `ProviderAvailabilityInput`, `provider_is_available`, `queue_terminal_frame`, `session_dir_name`, and `build_session_state_payload` are defined before route delegation steps use them.
