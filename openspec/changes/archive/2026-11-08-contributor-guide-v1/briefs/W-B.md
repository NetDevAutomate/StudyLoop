# Brief W-B — make a change, part A (four pages)

Read `00-common.md`, then `design.md` §2 (your rows), §3 (F7, F11, F12 especially), §6, and the
Terraform pages you mirror (fetch: Add a New Resource Type, Add a New Data Source Type, Bugs and
Enhancements) for *shape* only — StudyLoop's content comes from the tree.

| | |
| --- | --- |
| Branch | `feat/contributor-guide-b` from the scaffold sha given in your dispatch |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/contributor-guide-b` |
| Owns | `docs/contributor-cli.md`, `docs/contributor-web.md`, `docs/contributor-mcp.md`, `docs/contributor-doctor.md`, `evidence/W-B/` |
| Forbidden | every other `docs/` file, `mkdocs.yml`, `CHANGELOG.md`, any test or `src/` file |

Each page has the same spine, in this order, numbered: *where it lives* (real paths from the
tree, cited) → *the smallest complete example* (read an existing small one in the tree and point
at it by path; do not invent an API) → *its test* (the pattern the cookbook `docs/contributor-testing.md`
already shows; link, do not restate) → *the gate that proves it* (`just test-web`, `just test-js`,
the pytest path) → *what reviewers look for* (3-5 bullets).

## Pages

1. **`contributor-cli.md`** — Click commands (`@click.command`, NOT Typer) under `cli/_*.py`, how they are mounted in
   `cli/__init__.py` (read it: lazy mounting), `--help` text is documentation (the drift test
   resolves every fenced `studyloop …` example, so `--help` must be true), the CliRunner test.
2. **`contributor-web.md`** — FastAPI route under `web/routes/`, registration in `web/app.py`, the
   Alpine/HTMX/JS UI under `web/static/` (F12: not React), TestClient test, one Playwright journey
   in `tests/e2e/` using the hermetic world (`tests/e2e/_env.py`), `just test-web` and `just test-js`.
   Say plainly that `just e2e` is a release gate run by the maintainer, one per machine.
3. **`contributor-mcp.md`** — MCP tools under `mcp/`, parity with the CLI, the existing parity test
   (`test_mcp_session_parity.py` — verify the name), how a tool is exercised in a test.
4. **`contributor-doctor.md`** — a check under `doctor/`, the `CheckResult` shape (read it), honest
   wording rules, no side effects, how `studyloop doctor` is run in tests with fake binaries.

## Report

Common §5 plus: for each page, the one existing file you pointed at as "the smallest complete
example" and why it is the smallest.
