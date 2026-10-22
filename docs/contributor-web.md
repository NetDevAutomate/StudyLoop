# A Web Route and UI

<!-- facts: F7 F11 F12 -->

A web change is a FastAPI route in `packages/studyloop/src/studyloop/web/routes/`, registered in
`packages/studyloop/src/studyloop/web/app.py`, and an Alpine component in
`packages/studyloop/src/studyloop/web/static/` that calls it — Alpine, HTMX and plain browser
JavaScript, not React (F12). It is proved by a `TestClient` test, a `node --test` unit test for
the component, and one Playwright journey in `packages/studyloop/tests/e2e/`.

1. Start the app you will walk: `uv run studyloop web` serves `http://127.0.0.1:8567` (the port is
   `--port`; it prints a sign-in address with a token, open that; `--bind ADDRESS` also serves
   one other address of the machine behind Basic auth, `--lan` is deprecated). Then add the route module and
   `include_router` it in `web/app.py`.
2. Add or extend a component factory under `static/js/components/` and bind it in `index.html`.
3. Write the `TestClient` test and the component's `node --test` file.
4. Write one Playwright journey against the hermetic world in `tests/e2e/`.
5. Run `just test-web`, `just test-js` and the coverage gate below.

## 1. Where it lives

- Routes: one `APIRouter` per module in `packages/studyloop/src/studyloop/web/routes/`. The
  factory `create_app()` in `packages/studyloop/src/studyloop/web/app.py` imports each module
  and calls `app.include_router(<module>.router, prefix="/api")`; a developer-preview router
  (`exercises`) is included only when the server was started with `studyloop web --dev`.
- UI: `packages/studyloop/src/studyloop/web/static/index.html` is the one page. Component logic
  is a factory per file in `packages/studyloop/src/studyloop/web/static/js/components/`, imported
  by `packages/studyloop/src/studyloop/web/static/js/main.js` and assigned to `window`, because
  Alpine evaluates `x-data="todayPanel()"` in global scope (the header comment of `main.js` says
  why factories, not classes). Pure helpers live in
  `packages/studyloop/src/studyloop/web/static/js/lib/`. Vendored Alpine and HTMX are under
  `packages/studyloop/src/studyloop/web/static/vendor/`; there is no bundler and no build step.
- Tests: `packages/studyloop/tests/test_web_*.py` (in-process `TestClient`),
  `packages/studyloop/tests/js/*.test.js` (Node's runner) and `packages/studyloop/tests/e2e/`
  (a real server in a subprocess, driven by Playwright).

## 2. The smallest complete example

Read this slice top to bottom; every file is small enough to hold in your head.

1. Route: `packages/studyloop/src/studyloop/web/routes/now.py` (29 lines) — one `GET /now`
   with validated query parameters, returning the same contract as `studyloop now --json`.
2. Registration: the `app.include_router(now.router, prefix="/api")` line in
   `packages/studyloop/src/studyloop/web/app.py`.
3. UI: `packages/studyloop/src/studyloop/web/static/js/components/today-panel.js` fetches
   `/api/now` in its `init()`; the markup binds it with `x-data="todayPanel()"` in
   `packages/studyloop/src/studyloop/web/static/index.html`.
4. Route test: `packages/studyloop/tests/test_web_now.py` (46 lines) — patches the engine the
   route calls, builds `create_app(study_dirs=[])`, asserts status and payload keys.
5. Component test: `packages/studyloop/tests/js/today-panel.test.js` — stubs `fetch` by URL and
   proves the factory without a DOM.

```bash
uv run --group dev pytest packages/studyloop/tests/test_web_now.py -q
```

## 3. Its test

Two layers, both already shown in the [testing cookbook](contributor-testing.md):

- The `TestClient` shape is the
  [API template](contributor-testing.md#api-template-real-route-isolated-state): a synthetic
  course directory under `tmp_path`, never the learner's. Assert the refusal status **and** the
  absence of a side effect for an invalid request.
- The browser journey is
  [one real learner journey](contributor-testing.md#playwright-one-real-learner-journey). Start
  from `packages/studyloop/tests/e2e/test_contributor_browser_example.py`: `build_test_world()`
  and `start_server()` from `packages/studyloop/tests/e2e/_env.py` give you an isolated HOME,
  config, database and vault plus a real server on a port unique to your module; attach
  `ConsoleWatch` before navigating and call `diag` on failure.

## 4. The gate that proves it

```bash
just test-web
just test-js
uv run --group dev pytest packages/studyloop/tests/test_e2e_coverage_gate.py -q -k route
```

`just test-web` runs a fixed list of `test_web_*.py` files named in `Justfile`; a new file is not
in that list until you add it, so run yours focused as above and extend the list in the same pull
request. The default suite (`just test`) collects it regardless. `just test-js` runs
`node --test packages/studyloop/tests/js/*.test.js` (pass the glob, not the directory). Both are
in `just preflight` (F7).

The coverage gate reads the running app's route table and fails if a route has no test, or no
test that exercises a real server — which only a module under `packages/studyloop/tests/e2e/` or
a browser test is. Skipped and xfailing tests do not count; a waiver needs a written reason.

`just e2e` is the full Playwright suite (about eight minutes). It is a release gate run by the
maintainer, one run per machine: the recipe takes the lock `/tmp/studyloop-e2e.lock` and waits
for any other run (F7). The default `pytest` selection deselects `e2e` (F7), so a green default
run says nothing about your journey; run it focused with the cookbook's `just e2e <file>` form
once, on your own machine, and say so in the pull request.

## 5. What reviewers look for

- Query and body parameters are validated in the route signature (patterns, bounds), and the
  handler calls a service — it does not open the database or read config itself.
- The route is registered with the `/api` prefix and appears in `create_app()`, not in a
  side-effecting import.
- The component is a factory with no DOM access at construction, so `node --test` can load it;
  `fetch` and `window` are touched only inside methods.
- Locators in the journey are role, label or stable id, with Playwright `expect` doing the
  waiting — no `sleep`, no `nth(3)`, no JavaScript that changes state instead of clicking.
- A refused request is asserted twice: the status, and that nothing was written.
