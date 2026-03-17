# Design: studyctl doctor, upgrade, and install-mentor agent

**Date:** 2026-03-17
**Status:** Draft
**Author:** Andy Taylor + Claude Opus 4.6

## Problem

Users installing Socratic Study Mentor face a fragmented setup experience:
no single command validates the installation, no mechanism keeps packages/agents/DB
in sync, and no guided path helps non-technical users through end-to-end setup.
The tool spans multiple packages (studyctl, agent-session-tools), 6 AI tool
integrations, optional dependencies, database migrations, and cross-machine sync
— all of which can silently drift.

## Solution

Three components that work together:

1. **`studyctl doctor`** — read-only diagnostic engine
2. **`studyctl update` / `studyctl upgrade`** — update and upgrade mechanism
3. **Install-mentor agent** — tool-agnostic AI-guided setup using doctor as its backbone

## Design

### 1. `studyctl doctor` — Diagnostic Engine

A read-only command that inspects the full installation and reports categorised
health checks. Modelled after `brew doctor`.

#### Check Categories

| Category | Checks |
|----------|--------|
| **Core** | Python >= 3.12, studyctl installed + version, agent-session-tools installed + version, config file exists + valid YAML |
| **Database** | Review DB exists + schema current; sessions DB (agent-session-tools) exists + pending migrations. Each DB checked independently. Cross-package migration discovery via `importlib.util.find_spec("agent_session_tools")` — no hard dependency. |
| **Config** | Obsidian vault path valid, review directories exist, sync remote reachable (if `sync_remote` configured), knowledge bridging configured, `config init` has been personalised (key fields set beyond defaults), pandoc binary available (for content pipeline) |
| **Agents** | For each detected AI tool, check agent definition installed at expected path + current vs manifest hash (see Agent Manifest below) |
| **Optional deps** | Discovered via `importlib.util.find_spec()`: pymupdf, notebooklm-py, sentence-transformers, kokoro-onnx, textual, fastapi |
| **Voice** | TTS model downloaded (if kokoro-onnx importable) |
| **Updates** | studyctl version vs PyPI latest, agent-session-tools version vs PyPI latest |

#### Agent Install Paths

| Tool | Detection | Agent definition path |
|------|-----------|----------------------|
| Claude Code | `which claude` | `~/.claude/commands/socratic-mentor.md` |
| Kiro CLI | `which kiro` | `~/.kiro/agents/study-mentor/` |
| Gemini CLI | `which gemini` | Project-level `GEMINI.md` or `~/.gemini/agents/` |
| OpenCode | `which opencode` | `~/.config/opencode/agents/study-mentor.md` |
| Amp | `which amp` | Project-level `AGENTS.md` |
| Crush | `which crush` | `~/.config/crush/agents/` |

#### Agent Definition Manifest

A JSON file committed to the repo at `agents/manifest.json`:

```json
{
  "version": 1,
  "agents": {
    "claude/socratic-mentor.md": {"hash": "abc123...", "updated": "2026-03-17"},
    "kiro/study-mentor/agent.yml": {"hash": "def456...", "updated": "2026-03-17"}
  }
}
```

Updated automatically by a pre-commit hook or CI step whenever agent files change.
Doctor compares local file hashes against manifest hashes fetched from
`https://raw.githubusercontent.com/NetDevAutomate/socratic-study-mentor/main/agents/manifest.json`.

#### Check Result Schema

Each check returns:

```python
@dataclass
class CheckResult:
    category: str       # "core", "database", "config", "agents", "deps", "voice", "updates"
    name: str           # "python_version", "config_valid", "agent_claude", etc.
    status: str         # "pass", "warn", "fail", "info"
    message: str        # Human-readable description
    fix_hint: str       # Command or instruction to fix (empty if pass)
    fix_auto: bool      # True if `studyctl upgrade` can fix this automatically
```

#### Output Modes

- **Default (terminal):** Rich table with coloured pass/warn/fail/info markers,
  grouped by category, with a summary line:
  `"12 checks passed, 2 warnings, 1 failure. Run 'studyctl upgrade' to fix 2 issues."`
- **`--json`:** JSON array of CheckResult objects for machine parsing
- **`--quiet`:** Summary line only
- **`--category CATEGORY`:** Filter to specific category (e.g. `--category core`).
  Useful in CI where network-dependent checks (PyPI, sync remote) should be skipped.

#### Exit Codes

- `0` — all checks pass or info only (healthy, nothing actionable)
- `1` — one or more warn with `fix_auto: true`, or any fail (actionable issues exist)
- `2` — core fail (cannot function — missing package, corrupt DB)

Warnings without `fix_auto` (informational, e.g. "optional dep not installed")
do not elevate the exit code. Warnings WITH `fix_auto: true` (e.g. "update available",
"stale agent definition") return exit code 1 so the install-mentor fix loop
continues until they are resolved.

#### Implementation

New CLI module: `packages/studyctl/src/studyctl/cli/_doctor.py`

Checker functions registered in a list, each returning `list[CheckResult]`.
Categories are independent — a failure in one doesn't skip others.

For the PyPI version check: use `urllib.request` (stdlib, zero extra deps) to
query `https://pypi.org/pypi/studyctl/json` and compare against installed version.
Cache the result for 1 hour in `~/.cache/studyctl/pypi-check.json` to avoid
rate limits on repeated runs. Degrade gracefully on network failure (return
`info` status, not `fail`).

### 2. `studyctl update` + `studyctl upgrade`

#### `studyctl update` — Fetch metadata (fast, no changes)

- Query PyPI for latest versions of studyctl + agent-session-tools
- Query GitHub API for latest agent definition manifest hash
- Check both DBs for pending migrations
- Display what would be upgraded
- Exit code: always 0 (informational). Updates-available status conveyed via
  stdout and `--json` output, not exit code (avoids exit-code-1-means-error
  collision in scripts using `&&`).

#### `studyctl upgrade` — Apply updates

Runs each applicable upgrade step in order:

| Component | What it does | Rollback |
|-----------|-------------|----------|
| `packages` | Detect install method (uv/pip/brew) and use appropriate upgrade command | Previous version noted in output |
| `agents` | Download latest agent definitions from GitHub manifest, install for detected AI tools | Backs up existing to `~/.config/studyctl/agent-backups/YYYYMMDD/` |
| `database` | Run pending migrations on both review DB and sessions DB | DB backed up to `~/.config/studyctl/db-backups/DBNAME.bak.YYYYMMDD`. Prune backups older than 30 days. Abort upgrade if backup fails. |
| `voice` | Download/update kokoro TTS model | N/A |

#### Package Manager Detection

| Indicator | Manager | Upgrade command |
|-----------|---------|----------------|
| `uv tool list` contains studyctl | uv | `uv tool upgrade studyctl` |
| `brew list studyctl` succeeds | Homebrew | `brew upgrade studyctl` |
| `pip show studyctl` succeeds | pip | `pip install --upgrade studyctl` |
| None detected | Fallback | `pip install --upgrade studyctl` |

Detection order: uv → brew → pip. First match wins.

#### Flags

- `--dry-run` — preview what would change, no modifications
- `--component COMPONENT` — upgrade selectively: `packages`, `agents`, `database`, `voice`, `all` (default)
- `--force` — upgrade even if already current

#### Implementation

New CLI module: `packages/studyctl/src/studyctl/cli/_upgrade.py`

### 3. Install-Mentor Agent

A single tool-agnostic prompt file at `agents/shared/install-mentor.md` that
any AI coding assistant can use to guide a user through end-to-end setup.

#### Flow

```
detect environment → choose install method → install packages →
run config init → run doctor --json → fix issues → verify →
offer quick tour
```

#### Key Design Decisions

- **Contract is `studyctl doctor --json`** — the agent parses CheckResult objects
  and uses `fix_hint` to know HOW to fix each issue. The agent doesn't need to
  understand studyctl internals.
- **Fix loop with termination guard:** Run doctor → parse results → execute
  fix_hints for `fix_auto: true` items → explain manual items to user →
  re-run doctor → repeat. **Maximum 3 iterations.** If issues persist after
  3 cycles, present remaining issues to user with manual instructions and
  stop looping.
- **Tool-agnostic:** Works in Claude Code, Kiro CLI, Gemini CLI, OpenCode, Amp,
  or any tool that can run shell commands. No tool-specific APIs used.
- **Adaptive tone:** Explains what each step does and why, suitable for
  non-technical users. Uses Socratic questioning style consistent with the
  mentor's pedagogy.
- **Stateless:** Entirely driven by `studyctl doctor` output each iteration.
  No install state to manage.

#### Prompt Structure

```
Role: Socratic Study Mentor install assistant
Context: What studyctl is, what components exist, what doctor checks
Process: detect → install → configure → doctor-fix loop (max 3) → tour
Tools needed: Shell command execution only
Validation: studyctl doctor --json until exit code 0 or max iterations
Personality: Patient, explanatory, celebrates progress
```

#### Detection Logic (in prompt)

The agent checks for:
- OS (macOS/Linux) via `uname`
- Python version via `python3 --version`
- Package manager: `which uv`, `which brew`, `which pip`
- AI tools: `which claude`, `which kiro`, `which gemini`, `which opencode`, `which amp`
- Existing config: `test -f ~/.config/studyctl/config.yaml`

## CI/CD Pipeline

See [docs/ci-cd-pipeline.md](../ci-cd-pipeline.md) for the full workflow specification.

Three workflow tiers protect the upgrade path and Docker images:

### Nightly: Upstream Drift Detection

Runs on schedule (`cron: '0 3 * * *'`). Catches breaking changes from upstream
dependencies between releases.

1. Fresh install from PyPI on clean Ubuntu + macOS runners
2. Install all optional extras (`studyctl[all]`)
3. `studyctl doctor --json` → assert exit 0
4. Simulate upgrade: install previous PyPI release, then `studyctl upgrade`
5. Full test suite post-upgrade
6. If any step fails → auto-open GitHub issue with failing dep/version

### Pre-Release Gate

Triggered on release tags (`v*`) and manual dispatch. Must pass before PyPI
publish.

1. Tests upgrade path from N-1 → N version
2. Tests fresh install path from PyPI (using TestPyPI for pre-release)
3. Builds and tests Docker image
4. Runs `studyctl doctor` inside the container
5. All must pass before PyPI publish proceeds

### Docker Image Pipeline

Triggered after successful PyPI release or on Dockerfile changes.

1. Build `studyctl-web` image with server-side TTS
2. Run `studyctl doctor --json` inside container → assert exit 0
3. Health check: `curl localhost:8567` returns 200
4. TTS health check: generate test audio via API endpoint
5. Push to GitHub Container Registry (`ghcr.io/netdevautomate/studyctl-web`)
6. Tag with version + `latest`

### Version Compatibility Check

`studyctl upgrade` performs a pre-flight compatibility check before applying
changes:

- Fetches `compatibility.json` from the target release (hosted alongside
  the PyPI package metadata or in the GitHub repo)
- Compares installed dependency versions against known-compatible ranges
- Warns on known breaking changes with migration instructions
- `--dry-run` shows the full diff of what would change

```json
{
  "0.3.0": {
    "min_python": "3.12",
    "breaking": {"notebooklm-py": {"min": "0.3.4", "note": "API change in 0.4.0"}},
    "compatible": {"pymupdf": ">=1.23", "sentence-transformers": ">=2.2"}
  }
}
```

## Phase 2: Docker Web + Server-Side TTS (Future)

A lightweight Docker image running `studyctl web` with server-side TTS via
kokoro-onnx. Provides consistent high-quality voice across all devices without
browser TTS dependency.

```
docker run -v ~/study-cards:/data -p 8567:8567 studyctl-web
```

Architecture: FastAPI endpoint generates audio via kokoro → returns audio
stream over HTTP → browser plays via standard `<audio>` element. No audio
device passthrough needed.

This is scoped as a separate implementation after doctor/upgrade ships.

## Testing Strategy

- **doctor checks:** Unit test each checker function with mock filesystem/config.
  Integration test with a temp config + DB. Test cross-package migration
  discovery when agent-session-tools is/isn't installed.
- **update/upgrade:** Mock PyPI and GitHub API responses. Test dry-run mode.
  Test component-selective upgrades. Test package manager detection across
  uv/pip/brew (mock `which` and `subprocess` calls). Test DB backup creation,
  naming, and 30-day pruning. Test interrupted upgrade (kill mid-migration)
  leaves DB in recoverable state.
- **install-mentor:** Manual testing with each AI tool. Automated test that
  the prompt file is valid markdown and references exist. Test fix-loop
  termination at 3 iterations.
- **Exit codes:** Test all three exit code scenarios (0, 1, 2) end-to-end.
  Test that `fix_auto: true` warnings hold exit code at 1.

## File Locations

```
packages/studyctl/src/studyctl/cli/_doctor.py    # doctor command
packages/studyctl/src/studyctl/cli/_upgrade.py   # update + upgrade commands
packages/studyctl/src/studyctl/doctor/            # checker modules
packages/studyctl/src/studyctl/doctor/__init__.py
packages/studyctl/src/studyctl/doctor/core.py     # core checks
packages/studyctl/src/studyctl/doctor/database.py # DB checks (both review + sessions)
packages/studyctl/src/studyctl/doctor/config.py   # config checks (incl. pandoc)
packages/studyctl/src/studyctl/doctor/agents.py   # agent checks (per-tool paths)
packages/studyctl/src/studyctl/doctor/deps.py     # optional dep checks (importlib)
packages/studyctl/src/studyctl/doctor/updates.py  # version checks (urllib, cached)
agents/shared/install-mentor.md                   # agent prompt
agents/manifest.json                              # agent definition hashes
```

## Success Criteria

1. `studyctl doctor` identifies all installation issues on a fresh machine
2. `studyctl doctor --json` output is parseable by any AI coding assistant
3. `studyctl upgrade` brings a stale installation to current with one command
4. A user with zero Python experience can go from nothing to working setup
   using the install-mentor agent in any supported AI tool
5. `studyctl doctor` returns exit code 0 after a clean install + upgrade
6. Package manager detection correctly identifies uv, brew, and pip installs
7. Agent definition updates are detected and applied without manual intervention
