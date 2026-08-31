# Contributing to StudyLoop

Thank you for helping improve an AuDHD-aware learning tool. Contributions can
be code, documentation, accessibility feedback, screenshots, reproducible bug
reports, or honest accounts of where the workflow created too much friction.

## Supported release scope

The pre-release has five first-party mentor harnesses:

- Kiro CLI, Codex, and Claude Code are core.
- OpenCode and pi are preview integrations.

Do not add another harness to a drive-by pull request. Start with an issue that
defines its persona mechanism, launch and resume commands, session store,
exporter, health check, failure behavior, and live acceptance path.

## Development setup

```bash
git clone https://github.com/NetDevAutomate/StudyLoop.git studyloop
cd studyloop
uv sync --all-packages --all-extras
uv run playwright install chromium
```

The workspace contains two Python packages:

- `packages/studyloop` owns the learner-facing CLI, Web UI, mentor adapters,
  planning, review, and content workflows.
- `packages/agent-session-tools` owns session import, SQLite search, sync, and
  optional Obsidian mirroring.

Mentor assets live under `agents/`. Shared methodology belongs under
`agents/shared/`; harness-specific launch or export behavior belongs in that
harness's own directory.

## Test and evidence rules

Tests may use isolated deterministic fixtures. Those fixtures must remain in
the test tree and must not be selectable or packaged as product backends.
Product data, screenshots, demos, release notes, and manual acceptance evidence
must come from real behavior; never present placeholder data as a live result.

Before opening a pull request, run:

```bash
just release-check
just docs
```

For a narrow change, run the nearest focused tests while iterating, then the
release gate before handoff. If global checks have a known unrelated failure,
report it separately and include the narrower evidence for your change.

Do not copy a test total into a document or release note. The executing gate is
the authority and its current output belongs in machine-readable release
evidence. Automated green also does not replace a manual learner-journey check.

## Public documentation boundary

`mkdocs.yml` is an explicit allowlist. A new file under `docs/` is internal by
default and will not be published until it is deliberately rewritten for users
and added to the allowlist and navigation.

Keep these internal unless there is a specific reason to publish them:

- audits and release evidence;
- implementation plans and handoffs;
- architecture investigations and ADRs;
- agent instructions and model-review transcripts;
- historical debugging notes.

## Pull requests

Keep each pull request focused and answer:

1. What learner or contributor problem does this solve?
2. What changed?
3. Which automated checks passed?
4. Which live or manual journey was checked?
5. What remains unverified?

Never include credentials, private session transcripts, personal hostnames, or
unredacted local configuration in issues, fixtures, screenshots, or logs.
