# Provider-Aware Second Brain Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `0.3.0` provider-aware launcher that opens the exact configured Obsidian or xTiles destination from an explicit browser click while preserving provider consent, security boundaries, and installed-wheel behavior.

**Architecture:** A pure `second_brain.launch` resolver converts `SecondBrainConfig` plus request locality into an inert `LaunchTarget`. A single atomic configuration mutation service persists a validated xTiles destination through the CLI; no web mutation endpoint and no direct xTiles client are added. A read-only FastAPI endpoint exposes launch state to one Today action and provider cards in Settings.

**Tech Stack:** Python 3.12+, dataclasses, Typer/Click CLI, FastAPI, Alpine.js, Node test runner, Playwright, pytest, uv, Ruff, OpenSpec

**Spec:** `docs/handoffs/2026-09-04-second-brain-council-results.md`; Task 1 creates the normative OpenSpec change at `openspec/changes/provider-aware-second-brain-launcher/`

## Global Constraints

- Version target is `0.3.0`; do not alter `v0.2.1`.
- Keep the exact six-method `SecondBrain` protocol and pinned `BrainDescription` JSON keys unchanged.
- Do not add a direct xTiles API client or store xTiles credentials.
- Do not add a web endpoint that writes configuration.
- Do not launch applications server-side or automatically.
- Every navigation originates from one explicit browser user gesture.
- xTiles remains disabled until an exact validated destination exists.
- Provider selection remains explicit consent; a destination alone never selects xTiles.
- Obsidian launchability does not depend on vault writability.
- Treat non-loopback or ambiguous browser locality as unsafe for host-local Obsidian paths.
- Configuration writes are serialized, atomic, permission-preserving, and failure-clean.
- Never log complete xTiles URLs.
- Use TDD and include tests in each behavior commit.
- Static assets and APIs must work from an installed wheel.

---

### Task 1: Create and validate the `0.3.0` OpenSpec change

**Files:**
- Create via CLI: `openspec/changes/provider-aware-second-brain-launcher/.openspec.yaml`
- Create: `openspec/changes/provider-aware-second-brain-launcher/proposal.md`
- Create: `openspec/changes/provider-aware-second-brain-launcher/design.md`
- Create: `openspec/changes/provider-aware-second-brain-launcher/specs/second-brain-launcher/spec.md`
- Create: `openspec/changes/provider-aware-second-brain-launcher/tasks.md`

**Interfaces:**
- Consumes: council arbitration in `docs/handoffs/2026-09-04-second-brain-council-results.md`
- Produces: normative requirements for every following task

- [ ] **Step 1: Scaffold the change**

```bash
openspec new change "provider-aware-second-brain-launcher"
openspec status --change "provider-aware-second-brain-launcher" --json
```

Expected: scaffold exists with `.openspec.yaml` and ready artifact states.

- [ ] **Step 2: Write the proposal**

Include:

- problem: configured providers lack a browser navigation affordance;
- release: `0.3.0` additive feature;
- scope: launch resolver, atomic xTiles destination handoff, read API, Today/Settings UI;
- exclusions: direct xTiles client, server launch, automatic open, remote Obsidian support, web config writes;
- success: exact destinations, complete disabled states, installed-wheel proof.

- [ ] **Step 3: Write the design**

Lock these decisions:

```text
SecondBrainConfig + DeviceLocality -> LaunchTarget -> GET API -> explicit click
Assistant/xTiles connector -> CLI destination set -> atomic config mutation
```

Record the council decisions A1–A7, config-writer concurrency risk, conditional web authentication risk, static file ownership, and safe parallel waves.

- [ ] **Step 4: Write normative requirements and scenarios**

Requirements must cover:

1. Exact `LaunchTarget` fields and disabled-state invariant (`enabled=False` implies `href=None`).
2. Obsidian `Today.md` then vault-root target order.
3. Absolute-path percent encoding and symlink containment.
4. Local/read-only vault behavior and remote/unknown disabled behavior.
5. Exact xTiles allowlist, no credentials/port, real-URL evidence gate for query/fragment.
6. Destination does not select provider.
7. One atomic configuration owner and CLI-only mutation.
8. Read-only no-store API.
9. One Today action and muted/configurable Settings provider cards.
10. Explicit click only; no automatic or server-side launch.
11. Installed-wheel packaging and security evidence.

- [ ] **Step 5: Write tasks with the dependency graph from this plan**

Every task must declare blockers and validation. Keep frontend as one owner and config mutation as one owner.

- [ ] **Step 6: Validate the change**

```bash
openspec validate provider-aware-second-brain-launcher --type change --strict --no-interactive
```

Expected: valid.

- [ ] **Step 7: Commit the specification**

```bash
git add openspec/changes/provider-aware-second-brain-launcher
git diff --cached --check
git commit -m "spec(second-brain): define provider-aware launcher" \
  -m "Specify exact provider destinations, safe configuration ownership, explicit browser navigation, disabled states, and installed-wheel validation before implementation."
```

---

### Task 2: Make configuration mutation atomic and add xTiles destination handoff

**Files:**
- Modify: `packages/studyloop/src/studyloop/settings.py:319-339,500-534,721-780`
- Modify: `packages/studyloop/src/studyloop/cli/_brain.py:289-371`
- Test: `packages/studyloop/tests/test_second_brain_config.py`
- Test: `packages/studyloop/tests/test_cli_brain.py`
- Test: existing settings permission test file that currently covers `write_raw_config`

**Interfaces:**
- Produces: `SecondBrainConfig.xtiles_destination_url: str | None`
- Produces: `mutate_raw_config(mutator: Callable[[dict[str, Any]], None]) -> tuple[Path, dict[str, Any]]`
- Produces: `validate_xtiles_destination_url(value: str) -> str`
- Produces CLI: `studyloop brain destination set --provider xtiles --url URL`
- Preserves: `write_raw_config(data) -> Path` compatibility, now implemented atomically

- [ ] **Step 1: Write failing URL validation tests**

Cover:

```python
@pytest.mark.parametrize("url", [
    "http://xtiles.app/project/1",
    "https://user:pass@xtiles.app/project/1",
    "https://xtiles.app:8443/project/1",
    "https://evilxtiles.app/project/1",
    "https://mcp.xtiles.app/project/1",
    "https://xtiles.app/",
])
def test_rejects_unsafe_xtiles_destination(url: str) -> None: ...

@pytest.mark.parametrize("url", [
    "https://xtiles.app/project/abc",
    "https://app.xtiles.app/project/abc",
])
def test_accepts_reviewed_xtiles_destination_hosts(url: str) -> None: ...
```

Also assert query and fragment are rejected until the live evidence step proves they are required.

- [ ] **Step 2: Write failing config parsing and consent tests**

Assert:

- URL is parsed when present.
- URL with `provider: none` does not opt in.
- Invalid URL raises `ConfigError` before writes.
- Existing configs remain compatible.

- [ ] **Step 3: Write failing atomic mutation tests**

Test:

- unrelated keys survive;
- mode remains `0600`;
- sibling temporary file is cleaned after failure;
- destination remains byte-identical when replacement fails;
- two serialized mutations preserve both changes;
- mutation rereads after acquiring the lock.

- [ ] **Step 4: Implement the validated field and atomic writer**

Add:

```python
xtiles_destination_url: str | None = None
```

Use a lock sibling such as `config.yaml.lock`, `fcntl.flock(LOCK_EX)` on supported macOS/Linux, a `0600` sibling temp opened with `O_CREAT | O_EXCL`, `flush()`, `os.fsync()`, `os.replace()`, unconditional destination chmod, and temp cleanup in `finally`.

`mutate_raw_config()` must acquire the lock before loading current YAML. It passes the mutable mapping to the callback, validates the result, and atomically replaces the file.

- [ ] **Step 5: Move `brain enable` onto the mutation service**

Keep its existing behavior and messages. The callback changes only requested `second_brain` keys, then validates through `resolve_second_brain` before replacement.

- [ ] **Step 6: Add the destination CLI command**

Public syntax:

```bash
studyloop brain destination set --provider xtiles --url 'https://xtiles.app/...'
studyloop brain destination clear --provider xtiles
```

The setter validates before mutation. It must not change `second_brain.provider`. Human output prints host and success, never the complete URL. JSON output returns provider, configured boolean, and config path—never credentials or the full URL.

- [ ] **Step 7: Run targeted tests**

```bash
uv run pytest -q \
  packages/studyloop/tests/test_second_brain_config.py \
  packages/studyloop/tests/test_cli_brain.py \
  -k 'second_brain or destination or raw_config'
uv run ruff check packages/studyloop/src/studyloop/settings.py packages/studyloop/src/studyloop/cli/_brain.py
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add packages/studyloop/src/studyloop/settings.py \
  packages/studyloop/src/studyloop/cli/_brain.py \
  packages/studyloop/tests/test_second_brain_config.py \
  packages/studyloop/tests/test_cli_brain.py \
  packages/studyloop/tests/test_settings_custom.py
git diff --cached --check
git commit -m "feat(config): add validated second-brain destinations" \
  -m "Serialize and atomically replace configuration updates, then let the assistant persist an exact validated xTiles destination through the CLI without changing provider consent or adding a web write endpoint."
```

---

### Task 3: Resolve provider-neutral launch targets

**Files:**
- Create: `packages/studyloop/src/studyloop/second_brain/launch.py`
- Create: `packages/studyloop/tests/test_second_brain_launch.py`
- Assert unchanged: `packages/studyloop/tests/test_second_brain_protocol.py`

**Interfaces:**
- Consumes: `SecondBrainConfig.xtiles_destination_url`
- Produces:

```python
Provider = Literal["none", "obsidian", "xtiles"]
DeviceLocality = Literal["local", "remote", "unknown", "not_applicable"]

@dataclass(frozen=True)
class LaunchTarget:
    provider: Provider
    label: str
    href: str | None
    enabled: bool
    disabled_reason: str | None
    device_locality: DeviceLocality

    def to_json_dict(self) -> dict[str, object]: ...


def resolve_launch_target(
    config: SecondBrainConfig,
    *,
    locality: DeviceLocality,
) -> LaunchTarget: ...
```

- [ ] **Step 1: Write the complete failing truth-table test**

Cover:

- none;
- Obsidian local with `Today.md`;
- Obsidian local without `Today.md` falls back to vault root;
- read-only vault remains enabled;
- missing vault disabled;
- `Today.md` symlink escape disabled/falls back safely;
- remote/unknown Obsidian disabled;
- xTiles missing destination disabled;
- xTiles validated destination enabled;
- selected/inactive provider isolation;
- `enabled is False` always implies `href is None`.

- [ ] **Step 2: Write exact URI encoding tests**

Include spaces, Unicode, `#`, `?`, `%`, and nested folders. Expected URI is:

```python
f"obsidian://open?path={quote(str(target), safe='')}"
```

- [ ] **Step 3: Implement the minimal resolver**

The module imports `SecondBrainConfig` and standard library only. It never imports provider backends, never checks writability, and never performs network or subprocess operations.

- [ ] **Step 4: Prove stable contracts remain unchanged**

```bash
uv run pytest -q \
  packages/studyloop/tests/test_second_brain_launch.py \
  packages/studyloop/tests/test_second_brain_protocol.py \
  packages/studyloop/tests/test_second_brain_factory.py
```

Expected: pass; exact six-method protocol and `BrainDescription` keys unchanged.

- [ ] **Step 5: Commit**

```bash
git add packages/studyloop/src/studyloop/second_brain/launch.py \
  packages/studyloop/tests/test_second_brain_launch.py
git commit -m "feat(second-brain): resolve provider launch targets" \
  -m "Derive safe Obsidian and xTiles navigation state from explicit configuration and device locality without coupling launchability to provider publishing contracts."
```

---

### Task 4: Expose a read-only launch-target API

**Files:**
- Create: `packages/studyloop/src/studyloop/web/routes/second_brain.py`
- Modify: `packages/studyloop/src/studyloop/web/app.py:233-268`
- Create: `packages/studyloop/tests/test_web_second_brain.py`

**Interfaces:**
- Consumes: `resolve_launch_target(config, locality)`
- Produces: `GET /api/second-brain/launch-target`
- Response: exact `LaunchTarget.to_json_dict()` fields

- [ ] **Step 1: Write failing route tests**

Test all provider states with isolated config files. Assert:

- HTTP 200;
- exact response keys;
- `Cache-Control: no-store`;
- direct loopback client maps to `local`;
- non-loopback/unknown maps conservatively and disables Obsidian;
- xTiles remains `not_applicable` to locality;
- no POST/PUT/PATCH/DELETE mutation route exists;
- invalid config produces a safe disabled response or established API error without leaking the URL.

- [ ] **Step 2: Implement the route**

Use `load_settings().second_brain`, derive locality from the direct request peer only, call the pure resolver, and return a no-store response. Do not trust forwarding headers.

- [ ] **Step 3: Register the router before static mounting**

Add it to `create_app()` alongside existing API routers. Do not add middleware or config write behavior.

- [ ] **Step 4: Run targeted web tests**

```bash
uv run pytest -q packages/studyloop/tests/test_web_second_brain.py packages/studyloop/tests/test_web_now.py
uv run ruff check packages/studyloop/src/studyloop/web/routes/second_brain.py packages/studyloop/src/studyloop/web/app.py
```

- [ ] **Step 5: Commit**

```bash
git add packages/studyloop/src/studyloop/web/routes/second_brain.py \
  packages/studyloop/src/studyloop/web/app.py \
  packages/studyloop/tests/test_web_second_brain.py
git commit -m "feat(web): expose second-brain launch state" \
  -m "Serve inert, no-store provider launch targets while keeping configuration mutation and application launching outside the web boundary."
```

---

### Task 5: Add Today and Settings launcher states

**Files:**
- Modify: `packages/studyloop/src/studyloop/web/static/components.js`
- Modify: `packages/studyloop/src/studyloop/web/static/js/components/settings-panel.js`
- Modify: `packages/studyloop/src/studyloop/web/static/index.html`
- Modify/Create: focused JS unit tests under `packages/studyloop/tests/js/`
- Modify/Create: focused Playwright tests under `packages/studyloop/tests/`

**Interfaces:**
- Consumes: `GET /api/second-brain/launch-target`
- Produces: one Today action and two Settings provider cards

- [ ] **Step 1: Write failing JS state tests**

Define a pure helper/controller behavior and test:

- none -> no Today action;
- enabled Obsidian -> current-context custom URI;
- disabled Obsidian -> reason, no navigation;
- enabled xTiles -> `window.open(href, "_blank", "noopener,noreferrer")` once;
- disabled xTiles -> reason, no navigation;
- inactive provider -> muted Configure state;
- no action on initialization, refresh, publish, or wind-down.

- [ ] **Step 2: Extend Today state loading**

Fetch launch state during `todayPanel.init()` with the other read-only requests. Store the result before clicks so the click handler never awaits before opening a new tab.

- [ ] **Step 3: Add the Today launcher markup**

Render at most one selected-provider action near the Today heading or primary action. Disabled actions show the API reason. Do not render both provider choices on Today.

- [ ] **Step 4: Add the Settings provider cards**

Create a distinct “Second Brain” section separate from LLM Providers:

- active provider highlighted;
- inactive provider muted with CLI Configure guidance;
- xTiles missing destination shows the exact `studyloop brain destination set` command pattern;
- no full URL displayed;
- no web save button in `0.3.0`.

One frontend agent owns all three static files to avoid merge conflicts.

- [ ] **Step 5: Write failing browser tests before final markup wiring**

Route-stub the API and assert the full state matrix, exact hrefs, disabled controls, no auto-navigation, one navigation per click, and clean console. Do not actually open Obsidian in ordinary tests.

- [ ] **Step 6: Run JS and browser tests**

```bash
node --test packages/studyloop/tests/js/*.test.js
uv run pytest -q packages/studyloop/tests/test_web_settings_panel_e2e.py -k 'second_brain or launcher'
just test-browser-smoke
```

- [ ] **Step 7: Commit**

```bash
git add packages/studyloop/src/studyloop/web/static/components.js \
  packages/studyloop/src/studyloop/web/static/js/components/settings-panel.js \
  packages/studyloop/src/studyloop/web/static/index.html \
  packages/studyloop/tests/js \
  packages/studyloop/tests/test_web_second_brain_launcher_e2e.py
git commit -m "feat(web): add provider-aware second-brain launcher" \
  -m "Show one explicit provider action on Today and honest active, muted, and disabled states in Settings without adding automatic navigation or web configuration writes."
```

---

### Task 6: Prove packaging, security, and documentation

**Files:**
- Modify: installed-wheel smoke script/tests selected by existing CI conventions
- Modify: `docs/second-brain.md`
- Modify: `docs/setup-guide.md` if configuration examples require it
- Modify: `CHANGELOG.md`
- Create: `releases/v0.3.0.md`
- Modify: root `pyproject.toml`, `packages/studyloop/pyproject.toml`, and `uv.lock` for version `0.3.0`
- Update: `openspec/changes/provider-aware-second-brain-launcher/tasks.md`

**Interfaces:**
- Consumes: frozen resolver/API/UI contracts
- Produces: distributable `0.3.0` and validation evidence

- [ ] **Step 1: Validate one real xTiles project URL shape**

Run the existing opt-in xTiles journey using owner credentials. Record only scheme, hostname, port presence, query presence, and fragment presence—never the full URL. If query or fragment is required, update the OpenSpec, validator tests, and redaction rules before permitting it. Otherwise retain the strict rejection.

- [ ] **Step 2: Extend installed-wheel smoke coverage**

Build the wheel, install into a fresh environment, start the web app, request `/api/second-brain/launch-target`, and verify the packaged static assets contain the launcher markup/JS. The test must not import from the checkout.

- [ ] **Step 3: Run the security matrix**

Prove rejection of HTTP, userinfo, non-default ports, deceptive suffix hosts, connector host, Unicode/IDNA lookalikes, overlong URLs, unsupported query/fragment, and complete-URL logging. Prove no `subprocess`, AppleScript, `open`, `xdg-open`, or direct xTiles network client appears in the implementation diff.

- [ ] **Step 4: Update documentation and release metadata**

Document:

- exact Obsidian URI behavior and same-device limitation;
- xTiles assistant handoff command;
- disabled states and no generic fallback;
- no automatic launch;
- Settings is status/guidance only;
- source-checkout distribution model.

Bump both pyprojects and lockfile to `0.3.0`, add CHANGELOG/release note entries, and mark every OpenSpec task truthfully.

- [ ] **Step 5: Run the deterministic release spine**

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
node --test packages/studyloop/tests/js/*.test.js
uv run pytest -q
just test-web
just test-browser-smoke
just e2e
./scripts/build-release.sh
uv run python scripts/check-release-consistency.py --release
openspec validate --all --strict --no-interactive
```

Record exact exit codes, pass/skip counts, and artifact names.

- [ ] **Step 6: Archive or explicitly defer the OpenSpec change according to repository policy**

Do not let release consistency discover an unexplained active change. Sync canonical specs before archive when required.

- [ ] **Step 7: Commit release preparation**

```bash
git add docs CHANGELOG.md releases/v0.3.0.md pyproject.toml packages/studyloop/pyproject.toml uv.lock openspec
git diff --cached --check
git commit -m "chore(release): prepare 0.3.0" \
  -m "Document and version the provider-aware Second Brain launcher after full unit, browser, installed-wheel, security, and release-consistency validation."
```

---

### Task 7: Run the second model council review

**Files:**
- Create: `docs/handoffs/2026-09-04-second-brain-council-review-brief.md`
- Create: `docs/handoffs/2026-09-04-second-brain-council-review-results.md`

**Interfaces:**
- Consumes: final OpenSpec, plan, merge-base diff, commit claims, validation transcript, artifacts
- Produces: accepted findings and release decision

- [ ] **Step 1: Write the implementation review brief**

Include merge base, HEAD, ordered commit SHAs/messages, changed-file inventory, exact claims, tests and counts, artifacts, security matrix, deviations, and the nine review questions from the council results.

- [ ] **Step 2: Dispatch Claude Opus 5, GPT-5.6 Sol, and Qwen3 Coder Next independently**

Same brief, different families, read-only repository access. Persist each answer immediately.

- [ ] **Step 3: Arbitrate rather than average**

Publish agreement, divergence, coordinator choices, costs, and what the implementation brief got wrong.

- [ ] **Step 4: Fix every accepted blocker**

Use focused TDD commits. Re-run affected checks followed by the complete deterministic release spine.

- [ ] **Step 5: Final verification and push**

```bash
git status --short
MERGE_BASE=$(git merge-base v0.2.1 HEAD)
git log --oneline --decorate "$MERGE_BASE"..HEAD
git push origin main
```

Verify local HEAD equals `git ls-remote origin refs/heads/main`. Create/push the `v0.3.0` tag only after all release checks and final council blockers are clear, using the repository’s established release process.
