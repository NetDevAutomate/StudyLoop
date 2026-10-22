# Testing cookbook for contributors
<!-- facts: F7 F8 F11 -->

Pick the smallest tier that can prove your behaviour, write one focused test there, and copy the
structure of the two collected examples below, not their assertions. The five tiers, who runs each
and where, come first; the patterns the examples already show follow.

## Choose the tier first

1. **Default** — `just test`, which is `uv run --group dev pytest`: unit, CLI, `TestClient` and
   docs-truth tests. You run it locally; CI runs it on every push to `main` and every pull request targeting `main`. `pyproject.toml`
   deselects every other marker, so a green default run proves nothing about the tiers below.
2. **Integration** — `pytest -m integration`: real tmux and SQLite. Opt in locally when you touch
   sessions or history; CI runs the marker nightly at 03:00 UTC (`.github/workflows/nightly-uat.yml`).
3. **Browser (e2e)** — `just e2e`: Playwright journeys against a real server with fake agents. It
   takes a machine-wide lock (`/tmp/studyloop-e2e.lock`), so one run per machine: the maintainer runs
   it before a merge and CI runs the browser suite on pushes to `main` and pull requests to `main`. Run it yourself only when you
   touched the web UI, the session transports or `tests/e2e/`, and never start a second run beside it.
4. **Acceptance** — `just testacc`, which sets `STUDYLOOP_ACC=1`: a real harness through the real
   product surface. Opt-in on your own machine; it never runs in CI.
5. **UAT** — `just testuat`, which adds `STUDYLOOP_UAT=1`: release sign-off graded against a written
   rubric. Opt-in on top of acceptance; never in CI. Both are on [Acceptance testing](acceptance-testing.md).

Not sure? Start at 1 and move down only when the behaviour cannot be observed one tier up. See
[setup](contributing.md#development-environment) and the [code map](contributor-code-map.md).

## First make a small loop work

From the repository root, after installing `uv`, `just` and the required Python version:

```bash
just sync-web
uv run --group dev playwright install chromium
uv run --group dev pytest packages/studyloop/tests/test_contributor_examples.py -q
```

The browser twin of that example runs under `just e2e` with the file path as its argument
(tier 3 above). The two example files are real, collected regression tests, not pseudocode. Copy
their structure, not their assertions, for your feature. Use `just sync-full` when working across
optional extras. In a worktree, prefix `just` or `uv run` with `env -u VIRTUAL_ENV`.

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
release consistency and the specification check. It does **not** run the browser suite; that is
`just e2e`, tier 3 above. A green default run is not evidence that the opt-in tiers ran.

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

Re-run the one failing journey through `just e2e` with its file path, adding `--headed` to watch it
and `--tracing retain-on-failure` to keep a Playwright trace (the recipe passes extra arguments to
pytest). The helper's `diag` writes screenshot, HTML and console evidence on failure. Inspect the
reported artifact paths. Traces and HTML may contain everything the browser saw: only attach
reviewed, synthetic evidence to a public PR. Do not commit generated test artifacts. State which
browser, viewport and test command reproduced the failure.

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

Secret scanning runs server-side too. On a pull request, the `secrets` CI job runs detect-secrets
over the checkout, then trufflehog over the pull request's own commits. A verified or
unverifiable credential fails the job, and so does a base commit the job cannot resolve. To run
the same range through the redacting wrapper first, use
`uv run --group dev python scripts/security/trufflehog_redacted.py --base origin/main --head HEAD`.
The local run is stricter than CI: it also fails on revoked or fake keys. For the pins and their
limits, see `docs/security/trufflehog-ci.md` in the repository.

## Pull-request template

The template is the five questions on [Raising a pull request](contributor-pull-requests.md); this
page only says what the test evidence under question 3 should look like:

1. The regression test, and why it failed before the fix (an import error is not that reason).
2. The commands you ran, as typed, with their actual results, including skips and failures.
3. For a browser change: the journey, the viewport and a reviewed synthetic screenshot.
4. What you did not test, and why; a mock-backed test is not a live-provider verification.

Before requesting review: run `just preflight`, the relevant browser or acceptance tier, and
`git diff --check`; read the diff yourself. Do not paste credentials or personal paths in the PR,
and do not describe a local pass as a release.
