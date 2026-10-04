# Testing cookbook for contributors

You do not need to understand every suite to write a good first test. Start at the smallest boundary
that can prove the behaviour, then add a browser journey if the learner must interact with the UI.
See [setup](contributing.md#development-environment) and the [code map](contributor-code-map.md).

## First make a small loop work

From the repository root, after installing `uv`, `just` and the required Python version:

```bash
just sync-web
uv run --group dev playwright install chromium
uv run --group dev pytest packages/studyloop/tests/test_contributor_examples.py -q
just e2e packages/studyloop/tests/e2e/test_contributor_browser_example.py
```

The two example files are real, collected regression tests, not pseudocode. Copy their structure,
not their assertions, for your feature. Use `just sync-full` when working across optional extras.
In a worktree, prefix `just` or `uv run` with `env -u VIRTUAL_ENV`.

## Which test belongs where?

| Question | Test layer | Run from the root |
| --- | --- | --- |
| Is a rule, conversion or refusal correct? | Python unit/service test | `uv run --group dev pytest path/to/test_file.py -q` |
| Are CLI flags, messages and exit codes correct? | `click.testing.CliRunner` | Same focused pytest command |
| Does an endpoint validate input and call the correct service? | FastAPI `TestClient` | `just test-web` or its nearest `test_web_*.py` file |
| Does browser-side logic work independently of rendering? | Node's test runner, `tests/js/` | `just test-js` |
| Can a learner complete the flow in the real UI? | Python Playwright, `tests/e2e/` | `just e2e path/to/test_file.py` |
| Does the actual provider or external destination work? | Explicit opt-in integration/acceptance test | Follow [acceptance testing](acceptance-testing.md), never enable it casually |
| Are published commands and capability claims still true? | Documentation contract test | Relevant `test_docs_*.py`, plus `just docs` |

`just preflight` runs lint, type checks, the default Python suite, JavaScript tests, strict docs,
release consistency and the specification check. It does **not** run the full Playwright suite.
`just e2e` does; run it for changes to Web UI, session transports or browser tests. It serializes
browser runs with a machine-wide lock. Do not bypass that lock to run a second browser suite.
The default pytest selection excludes opt-in integration, browser and live-provider markers.
A green default run is not evidence that those workflows ran.

Keep test filenames unique across `tests/` and its subdirectories. The coverage collector also
collects with pytest's prepend import mode; two files with the same basename can pass a focused
run but break that collection. New routes, CLI commands, navigation views and rendering surfaces
must satisfy `test_e2e_coverage_gate.py`. Its proof comes from runnable tests: skipped or actively
xfailing tests do not count. Add a real journey, not a textual reference or a waiver to hide missing
coverage. Run the gate and its self-tests when adding test files:

```bash
uv run --group dev pytest packages/studyloop/tests/test_e2e_coverage_gate.py packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
```

## Write a test that can catch the bug

Use **arrange → act → assert**, with one named behaviour per test. First watch it fail for the
intended reason; an import error is not the regression you meant to demonstrate. After the fix,
check that reverting the relevant behaviour would break the assertion.

- Assert the returned value **and** the relevant side effect: one saved record, no subprocess,
  unchanged file, or persisted state after reload. An exit code alone rarely proves enough.
- Cover a normal input, an invalid input and a refused operation. Add duplicate/retry, timeout,
  cancellation, stale state and migration cases when the feature crosses those boundaries.
- Parameterize independent input cases. Do not combine a whole feature into one test whose
  early failure hides every later assertion.
- Patch the external boundary where the consumer looks it up, not a distant definition that the
  consumer has already imported. Do not mock the function whose behaviour you are testing.
- Test semantic behaviour, not private implementation details or incidental wording, unless the
  exact wording is itself the public contract (for example a safety confirmation).

### Unit and CLI template: refusal means nothing executed

The maintained [unit/CLI example](https://github.com/NetDevAutomate/StudyLoop/blob/main/packages/studyloop/tests/test_contributor_examples.py)
creates a synthetic practice deck in `tmp_path`, checks command lookup, then proves that a
non-interactive CLI invocation without approval never reaches the verifier. Its core pattern is:

```python
def forbidden_verifier(*args, **kwargs):
    pytest.fail("The verifier must not run without approval")

monkeypatch.setattr(practice_cli, "verify_practice_task", forbidden_verifier)
result = CliRunner().invoke(
    practice_cli.practice_group,
    ["verify", str(deck_path), "--task", "1", "--run-command"],
)
assert result.exit_code == 2
assert "nothing executed" in result.output
```

This excerpt needs the imports and `deck_path` fixture in the linked file. It is a CLI-boundary test,
not proof of all service-level security. See `test_practice_verify.py` for the service's independent
confirmation gate, changed-command protection and database assertions.

### API template: real route, isolated state

Start with the fixture in `packages/studyloop/tests/test_web_app.py`: create synthetic course
files under `tmp_path`, call `create_app(study_dirs=[str(course_dir)])`, and use `TestClient`.
For a new route, put its tests beside the nearest route tests and follow their authentication
and lifecycle setup. A minimal shape is:

```python
with TestClient(create_app(study_dirs=[str(course_dir)])) as client:
    response = client.get("/")
assert response.status_code == 200
assert "text/html" in response.headers["content-type"]
```

`course_dir` must be your temporary fixture, never the learner's course directory. For a write
endpoint, also check the response schema and the stored result. For a refused request, assert
both the refusal status and absence of side effects. Endpoint tests cannot prove focus, keyboard
behaviour, rendering, or WebSocket behaviour in a browser.

## Playwright: one real learner journey

The application uses **pytest with Python Playwright**, not the website's React stack or a new
TypeScript test runner. Start from the complete
[browser example](https://github.com/NetDevAutomate/StudyLoop/blob/main/packages/studyloop/tests/e2e/test_contributor_browser_example.py).
It captures a synthetic thought through the UI and proves that a fresh browser context can read it,
without reusing the first context's memory or local storage.

The fixture pattern matters as much as the clicks:

1. `build_test_world(tmp_path_factory.mktemp(...), port=...)` creates isolated HOME, configuration,
   database, plans, vault and working directories. `start_server(world)` starts the real app.
2. A yielding fixture always calls `server.stop()` in `finally`. Use an unused test port; search
   existing tests first. Port `18611` is reserved for the developer's live server.
3. Attach `ConsoleWatch` before navigation. Drive the learner's action in the browser; assert
   visible results, persistence and clean browser/server diagnostics. Call `diag` on failure.

For a mentor flow, opt into `fake_agent=True` using the existing environment helper. A fake agent
removes provider cost and nondeterminism; it does not replace the app, its routes or its database.
Never point a test at your running personal StudyLoop instance.

### Locator and waiting template

```python
page.keyboard.press("p")
page.locator(".quick-park-input").fill("Why does this example persist?")
page.get_by_role("button", name="Park it", exact=True).click()
expect(page.locator(".quick-park-overlay")).to_be_hidden()
page.locator("#parking-lot-toggle").click()
expect(page.locator("#parking-panel")).to_be_visible()
expect(page.locator("#parking-panel").get_by_text(
    "Why does this example persist?", exact=True
)).to_be_visible()
```

Use the full example for imports, navigation, readiness and teardown. Prefer role/name or label
locators because they express what the learner can find. Stable IDs are appropriate where the
existing UI has no suitable accessible name; avoid positional selectors such as `nth(3)`.
Playwright's `expect` retries until the observable condition holds. Do not replace it with a
fixed sleep, a blanket timeout increase, or JavaScript that changes the application's state
instead of performing the action under test.

API seeding is useful for **setup**. It is not a substitute for clicking Save when Save is what
the test claims to prove. Reload to test persistence; do not infer a database write from an
optimistic UI update. Test keyboard access, escape/cancel, focus recovery and a narrow viewport
for new controls. Accessibility automation complements, rather than replaces, those checks.

### Debug a failure without hiding it

```bash
just e2e packages/studyloop/tests/e2e/test_contributor_browser_example.py --headed --tracing retain-on-failure
```

The helper's `diag` writes screenshot, HTML and console evidence on failure; pytest-playwright
can retain traces. Inspect the reported artifact paths. Traces and HTML may contain everything
the browser saw: only attach reviewed, synthetic evidence to a public PR. Do not commit generated
test artifacts. State which browser, viewport and test command reproduced the failure.

If startup reports an occupied port, stop the test process you own or choose an unused test port;
do not kill an unknown listener. If a browser is missing, reinstall Chromium using the same venv's
Playwright command. If a test skips, read the reason: missing optional dependencies are not a pass.

## Protect the developer and the learner

The shared `conftest.py` isolates state and checks for writes outside test-owned locations. Extend
those fixtures rather than setting HOME to your real home or copying the entire parent environment.
Use `tmp_path` for files; use the established temporary database helpers for persistence. Close
connections and stop child processes even after assertions fail.

No real API keys, cloud resources, tmux sessions, Obsidian vaults, xTiles projects, transcript
archives or Kubernetes contexts belong in the default suite. Live tests need explicit opt-in,
a named disposable target, timeouts, cleanup of only test-owned resources and a clear cost boundary.
Do not weaken a guard simply because it catches your new test.

## Pull-request template

Copy this into the PR description and fill only with evidence you have:

```markdown
## Problem and learner outcome
Issue: #...
Before:
After:

## Scope
Changed:
Deliberately not changed:
Privacy, permissions, migration or compatibility implications:

## Evidence
- Regression test and why it failed before the fix:
- Commands run and actual results (include skips/failures):
- Browser journey, viewport and reviewed synthetic screenshot if relevant:
- Not tested, and why:

## Documentation
- User guide / contributor guide / specification updated:
- Unreleased changelog entry:
- AI assistance used, if any:
```

Before requesting review: run `just preflight`, the relevant browser/acceptance checks, and
`git diff --check`; read the diff yourself. Do not paste credentials or personal paths in the PR.
Do not describe a mock-backed test as a live provider verification, or a local pass as a release.
