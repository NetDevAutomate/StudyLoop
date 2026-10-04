# Find your way around the code

Start with one learner action, not the whole repository. Run it locally, find the nearest test,
and follow the request into the service that owns the behaviour. Return to the
[contributor guide](contributing.md) for setup and pull-request policy, or open the
[testing cookbook](contributor-testing.md) when you are ready to prove a change.

## Two applications, not two front ends of the same build

StudyLoop's application lives in this Python workspace. Its browser UI is FastAPI with Alpine,
HTMX and browser JavaScript under `packages/studyloop/src/studyloop/web/static/`.
It is **not a React application**. The public studyloop.dev website is a separate repository,
[StudyLoopSite](https://github.com/NetDevAutomate/StudyLoopSite), with its own build and checks.
A website preview does not test the application's browser behaviour.

Session Weaver is part of this workspace's session-memory tooling, not a prerequisite clone
of another public repository. Changes to import or recall usually belong in
`packages/agent-session-tools/`.

## A map for your first change

Paths below are relative to the repository root. Within `packages/studyloop/src/studyloop/`:

| If you are changing… | Start here | Then look for proof in… |
| --- | --- | --- |
| CLI arguments, output or confirmation | `cli/` | `packages/studyloop/tests/test_cli*.py` and feature-specific CLI tests |
| A browser action or endpoint | `web/routes/`, `web/app.py`, `web/static/` | `test_web_*.py`, `tests/js/`, `tests/e2e/` under the StudyLoop package |
| Planning, practice or review behaviour | `planning/`, `learning/`, `review_db.py` | Feature-specific tests beside `test_practice_verify.py` |
| Session start, resume or terminal transport | `session/`, `session_runtime/`, `adapters/` | Session tests and the session-authority contract |
| Mentor instructions and recording protocol | Root `agents/shared/` and per-harness `agents/` directories | Adapter parity and documentation contract tests |
| Course ingestion and generated artefacts | `content/`, especially `content/schemas.py` | Content/schema tests; use synthetic source material |
| Notes and optional destinations | `second_brain/`, `notes.py`, `markdown_notes.py` | Second-brain unit tests; explicitly opted-in destination tests |
| Settings, persistence or diagnostics | `settings.py`, `db.py`, `doctor/`, relevant service | Existing migration, isolation and doctor tests |

For session memory, use `packages/agent-session-tools/src/agent_session_tools/`:

- `exporters/` and `export_sessions.py`: harness transcripts into the session store.
- `query_sessions.py`, `query_logic.py`, `retrieval.py`, `query_encoders.py`: query entry points
  and retrieval. Follow the current call chain before changing ranking.
- `context/`, `migrations.py`, `schema.sql`: structured records, evidence and storage evolution.
- `mcp_server.py`: the session-memory MCP boundary. StudyLoop also has its own `mcp/` package;
  identify which server owns the tool before editing it.

Names are navigation hints, not permission to bypass a service's API. Search for callers and tests
before moving code. For example:

```bash
rg -n 'verify_practice_task|peek_verification_command' packages
rg -n 'parking-lot-toggle|/api/parking' packages/studyloop
rg -n 'record_plan_learning' packages agents/shared
```

## Follow a change through its boundaries

For a browser feature, trace **learner action → browser handler → route → application service →
storage or adapter → response → visible result**. Each arrow is a possible failure boundary.
Find the route registration in `web/app.py`, not just a similarly named module.

Keep request parsing and presentation in the route or CLI command. Put reusable policy in the
owning service. CLI, Web UI and MCP should share that policy; one presentation layer should not
import another's private helper. Terminal ownership belongs to the existing session machinery,
not a second PTY manager in an optional integration.

An instructive existing example is practice verification:

1. `cli/_practice.py` loads the command for display and obtains consent.
2. `learning/practice.py` reloads the deck and checks that the exact confirmed command still matches.
3. Only then can execution and recording proceed. A changed file must not turn approval of one
   command into approval of another.

`content/schemas.py` defines the JSON contract. `verification.setupCommand` is currently surfaced
as metadata; it is **not an automatically executed setup hook**. See the
[optional-module proposal](contributor-modules.md) before designing around it.

## Choose the smallest owning layer

- A label fix usually belongs in the UI and a focused UI assertion, not a new service abstraction.
- A rule used by CLI and Web UI belongs below both, with direct tests plus thin adapter tests.
- An external dependency belongs behind a narrow adapter. Fake that boundary in deterministic tests;
  keep the policy and persistence real.
- A persisted format change needs migration, existing-data and rollback/recovery consideration.
  Do not fix an old database by assuming every learner can delete it and start again.
- A technology-specific workflow should be optional. The core remains topic-agnostic and must
  start and work without that technology installed.

## Read the contract before changing it

The [architecture overview](architecture.md) introduces the system. Detailed decisions live in
[ADRs](https://github.com/NetDevAutomate/StudyLoop/tree/main/docs/adr),
[current architecture](https://github.com/NetDevAutomate/StudyLoop/blob/main/docs/architecture/current.md)
and the [session-authority contract](https://github.com/NetDevAutomate/StudyLoop/blob/main/docs/architecture/session-authority.md).
Public capability specifications live under `openspec/specs/`.

For a new capability, discuss an issue and an OpenSpec proposal before building the whole integration.
For a lasting architectural decision, add an ADR rather than rewriting an old decision. Do not add
private audit notes, session histories or implementation handoffs to public documentation.

## A useful first pull request

Find one confusing error, missing refusal test, keyboard problem or inaccurate sentence. State the
observable behaviour, add the nearest failing test, make the smallest change, and update the guide
that a learner would read. Use the [PR template](contributor-testing.md#pull-request-template) to
record what you actually checked, including what you could not check.
