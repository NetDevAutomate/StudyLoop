# AGENTS.md — working on the StudyLoop repository

This file is for coding agents (and people) changing this repository. It is not the study mentor.

## The learner persona is not here

A study session's mentor persona is built by `studyloop study` from `agents/shared/personas/` and written
into the session directory it launches the harness in, once per session. That per-session `AGENTS.md` is
what Codex, Grok Build and pi read. The tracked Codex/Grok definition, `agents/codex/AGENTS.md`, is not
linked here either: `studyloop install agents` never writes to this checkout.

## What this repository is

A `uv` workspace: `packages/studyloop` (CLI, web dashboard, MCP server) and `packages/agent-session-tools`
(session export, search and maintenance). Mentor definitions for the six harnesses live under `agents/`.
Start with [CONTRIBUTING.md](CONTRIBUTING.md), then the `docs/contributor-*.md` set (code map, testing,
conventions, harnesses and agents, changelog, pull requests).

## Gates

- The recipes live in the `Justfile`. `just preflight` is the pre-push gate: lint, type checks, the default
  Python suite, JavaScript tests, strict docs, release consistency, spec check.
- Run Python tools through the workspace environment: `uv run pytest`, `uv run ruff check`,
  `uv run ruff format --check`, `uv run pyright`.
- The browser suite is `just e2e`. It takes a machine-wide lock and fixed ports, so run one at a time.
- The pre-commit hook (`uv run pre-commit install`) runs the secret scanners. Do not bypass it with
  `--no-verify` and do not add allowlist pragmas to get past it.

## Two rules agents keep tripping on

1. **Persona edits need a manifest update.** `agents/manifest.json` records the first 16 hex digits of the
   SHA-256 of every tracked definition. Edit one of those files and update its `hash` in the same commit;
   `packages/studyloop/tests/test_install_agent_contracts.py` fails until you do.
2. **`reviews/` is gitignored.** Review reports written there are never committed. Anything that has to
   ship belongs in `docs/`, an ADR or the changelog.
