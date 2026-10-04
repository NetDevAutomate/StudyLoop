# Find your way around the code

<!-- facts: F7 F12 F16 -->

Start with one learner action, not the whole repository. Run it locally, find the nearest test,
and follow the request into the service that owns the behaviour. The table under *A map for your
first change* tells you which guide page owns each kind of change.

## Two applications, not two front ends of the same build

StudyLoop's application lives in this Python workspace. Its browser UI is FastAPI with Alpine,
HTMX and browser JavaScript under `packages/studyloop/src/studyloop/web/static/`.
It is **not a React application**. The public studyloop.dev website is a separate repository,
[StudyLoopSite](https://github.com/NetDevAutomate/StudyLoopSite), with its own build and checks;
a website preview does not test the application's browser behaviour.

Session memory is the second package in this workspace, `packages/agent-session-tools/`: harness
transcripts are exported into a session store and queried from there. It has its own MCP server
(`mcp_server.py`); StudyLoop has another under `mcp/`. Identify which server owns a tool before
editing it.

## Which layer owns what

Within `packages/studyloop/src/studyloop/`, three thin surfaces share one set of services:

| Layer | Directory | Owns | Must not |
| --- | --- | --- | --- |
| Surfaces | `cli/` (Click, lazily mounted in `cli/__init__.py`), `web/routes/` + `web/static/`, `mcp/tools.py` | Parse input, call one service, present the result | Hold policy, or import another surface's private helper |
| Services | `learning/`, `planning/`, `content/`, `session/`, `doctor/`, `second_brain/` | The rules, shared by all three surfaces | Know which surface called them |
| Storage and settings | `db.py`, `review_db.py`, `review_loader.py`, `settings.py`, `state.py` | Persistence, migrations, config resolution | Be bypassed by a surface writing files itself |
| Harness boundary | `adapters/`, `harnesses.py`, `agent_launcher.py`, root `agents/` | Launching a coding harness and the mentor it runs | Grow a seventh harness (see [Harnesses and Agents](contributor-harnesses-agents.md)) |

## Follow one request through the layers

The *now* recommendation is the same decision reached from three surfaces, and
`packages/studyloop/tests/test_now_plan_guidance.py` pins that the CLI and web JSON are identical:

1. **CLI** -- `studyloop now --energy low` is mounted by `cli/__init__.py`'s `lazy_subcommands`
   table and lands in `cli/_now.py`, which parses options, calls
   `learning.decision.build_now_plan(...)` and renders the plan with Rich (or `--json`).
2. **Web** -- `web/static/js/components/today-panel.js` fetches `/api/now`; `web/app.py` mounts
   `now.router` under `/api`; `web/routes/now.py` reads the query, calls the same
   `build_now_plan(...)` and returns the JSON the panel renders.
3. **MCP** -- `get_next_action` in `mcp/tools.py` calls `build_now_plan(...)` for a harness.

One search shows the whole fan-in; a change to the recommendation belongs in `learning/decision.py`,
and the three callers only change if their input or output shape does:

```bash
rg -n 'build_now_plan' packages/studyloop/src/studyloop/cli packages/studyloop/src/studyloop/web/routes packages/studyloop/src/studyloop/mcp
```

Tests follow the same shape: `test_learning_decision.py` for the engine, `test_web_now.py` for
the route, `test_now_plan_guidance.py` for the parity.

## A map for your first change

A change of one kind lands in one place and is proved by one guide page:

| If you are changing… | It lands in | Guide page |
| --- | --- | --- |
| A CLI command, option or `--help` text | `cli/_<area>.py`, mounted in `cli/__init__.py` | [A CLI Command](contributor-cli.md) |
| A browser action, endpoint or panel | `web/routes/`, `web/static/js/components/` | [A Web Route and UI](contributor-web.md) |
| A tool a harness can call | `mcp/tools.py`, parity with the CLI | [An MCP Tool](contributor-mcp.md) |
| A diagnostic | `doctor/` | [A Doctor Check](contributor-doctor.md) |
| How a harness launches, or what the mentor says | `adapters/`, root `agents/` | [Harnesses and Agents](contributor-harnesses-agents.md) |
| What generated JSON may contain, or how it is produced | `content/schemas.py`, `content/generators/` | [Content Schemas and Pipeline](contributor-content.md) |
| A public page | `docs/`, `mkdocs.yml` | [Documentation](contributor-documentation.md) |
| Which tier a test runs in, or a new test pattern | `packages/studyloop/tests/` | [Testing Cookbook](contributor-testing.md) |

Planning, practice and review behaviour live in `learning/`, `planning/` and `review_db.py`; notes
and optional destinations in `second_brain/`, `notes.py`, `markdown_notes.py`; session start,
resume and terminal transport in `session/` and `adapters/`. Each has tests named for it --
[Conventions](contributor-conventions.md) states the `test_<area>_*.py` rule.

## Follow a change through its boundaries

For a browser feature, trace **learner action → browser handler → route → service → storage or
adapter → response → visible result**. Each arrow is a possible failure boundary. Find the route
registration in `web/app.py`, not just a similarly named module.

An instructive existing example is practice verification:

1. `cli/_practice.py` loads the command for display and obtains consent.
2. `learning/practice.py` reloads the deck (`load_practice_deck`) and checks that the exact
   confirmed command still matches.
3. Only then can execution and recording proceed. A changed file must not turn approval of one
   command into approval of another.

```bash
rg -n 'def load_practice_deck' packages
```

`content/schemas.py` defines the JSON contract. `verification.setupCommand` is surfaced as
metadata; it is **not an automatically executed setup hook**. Read the
[optional-module proposal](contributor-modules.md) before designing around it.

## Choose the smallest owning layer

- A label fix belongs in the UI and a focused UI assertion, not a new service abstraction.
- A rule used by CLI and Web UI belongs below both, with direct tests plus thin surface tests.
- An external dependency belongs behind a narrow adapter. Fake that boundary in deterministic
  tests; keep the policy and persistence real.
- A persisted format change needs a migration, an existing-data test and a recovery path. Do not
  fix an old database by assuming every learner can delete it and start again.
- A technology-specific workflow is optional. The core stays topic-agnostic and must start and
  work without that technology installed.

## Read the contract before changing it

The [architecture overview](architecture.md) introduces the system. Detailed decisions live in
[ADRs](https://github.com/NetDevAutomate/StudyLoop/tree/main/docs/adr) and the
[session-authority contract](https://github.com/NetDevAutomate/StudyLoop/blob/main/docs/architecture/session-authority.md);
both are source-only, off this site by design. Public capability specifications live under
`openspec/specs/`, and [Conventions](contributor-conventions.md) says when a change needs an
OpenSpec proposal or an ADR.

## A useful first pull request

Find one confusing error, missing refusal test, keyboard problem or inaccurate sentence. State the
observable behaviour, add the nearest failing test, make the smallest change, and update the guide
a learner would read. Then follow [Raising a Pull Request](contributor-pull-requests.md).
