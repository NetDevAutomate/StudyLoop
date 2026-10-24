# Conventions

<!-- facts: F1 F7 F13 F16 -->

Three naming systems meet in this repository: code and tests are named by the **area** they
belong to, behaviour changes are recorded as **OpenSpec changes** under `openspec/changes/`, and
lasting decisions are **ADRs** under `docs/adr/`. This page gives the rule for each; the
[pull-request page](contributor-pull-requests.md) owns the branch, commit-subject and PR-title grammar.

## Code: name the area, not the verb

1. **Modules.** One module per area inside `packages/studyloop/src/studyloop/`: a CLI command
   file is `cli/_<area>.py` (leading underscore -- it is mounted by name in `cli/__init__.py`,
   never imported by users); a web route file is `web/routes/<area>.py`; shared behaviour is a
   module or package named for the rule it holds (`learning/decision.py`, `planning/store.py`),
   never `utils` or `helpers`.
2. **Tests.** `packages/studyloop/tests/test_<area>_<what>.py`, where `<area>` is the directory or
   surface the test proves: `test_web_now.py`, `test_content_schemas.py`, `test_cli_plan.py`,
   `test_adapter_parity.py`, `test_docs_drift.py`. The prefix is how a reader finds a suite and
   how `just test-web` and `just test-content` group the files they list, so a new area gets a new
   prefix, not a suffix. Test helpers that are not tests start with an underscore
   (`_content_generator.py`, `_fake_agent.py`) so pytest never collects them.
3. **Fixtures.** Shared fixtures live in `packages/studyloop/tests/conftest.py`. Autouse isolation
   fixtures are named `_isolate_<what>` and fail a test that writes to the real config directory,
   vault or tmux server; named fixtures say what they give you (`mux_harness`, `tmp_path`). Data
   fixtures are files under `packages/studyloop/tests/fixtures/`. A fixture that only one file uses
   stays in that file.
4. **Tiers.** A test outside the default tier carries one marker from `pyproject.toml`:
   `integration`, `e2e`, `live_kiro`, `live_provider`, `live_obsidian`, `live_xtiles`,
   `acceptance`, `uat`. All eight are deselected by default (F7); a test with no marker must pass
   on a clean machine with no harness, browser or network.

## Scopes: the word in the commit is the directory in the tree

The scope in `<type>(<scope>): …` is the smallest stable subsystem the change lands in, and it
maps to a place in the tree. Use the existing word when one fits:

| Scope | Lands in |
| --- | --- |
| `web` | `web/routes/`, `web/static/`, `web/app.py` |
| `mcp` | `mcp/tools.py`, `mcp/server.py` |
| `doctor` | `doctor/` |
| `agents` | root `agents/`, `adapters/`, `harnesses.py` |
| `plan` | `planning/`, `cli/_plan.py` |
| `now` | `learning/decision.py`, `cli/_now.py`, `web/routes/now.py` |
| `session` | `session/`, `session_state.py`, `agent_launcher.py` |
| `content` | `content/` |
| `openspec` | `openspec/changes/`, `openspec/specs/` |
| `contributing` | `docs/contributor-*.md`, `docs/contributing.md` |

A change that touches several of these is cross-cutting: omit the scope rather than invent one.

## OpenSpec changes: when and how

Open a change for a behaviour or design change (a new option, a changed flow, a new module); a
small fix with a test goes straight to a pull request.

1. Create `openspec/changes/<id>/` with `proposal.md` (what and why), `design.md` (how, and the
   decisions taken), `tasks.md` (the ordered work) and `specs/<capability>/spec.md` holding the
   **delta** to the living spec in `openspec/specs/<capability>/spec.md`. Requirements use SHALL
   and each has at least one `#### Scenario:` with WHEN/THEN. **One requirement states one
   behaviour**, and its body (the prose before the first scenario; fenced code does not count) stays
   under 500 characters -- the validator fails a longer one. When a requirement wants to say more,
   that is two requirements, or examples and edge cases that belong in scenarios; a conditional
   lead-in ("When the learner has an active plan: ...") is part of every requirement it governs, so
   repeat it rather than leave a SHALL without its condition.
2. Add `.openspec.yaml` (`schema: spec-driven`, `created:`). A documentation-only change declares
   `skip_specs: true` there, as `openspec/changes/contributor-guide-v1/.openspec.yaml` does: the
   `openspec` CLI refuses a change with no spec delta unless the flag is set (this change failed
   `spec-check` until it was added), so the flag is the reviewer's cue that "no delta" was a choice.
3. Validate the structure with `openspec validate --specs --all --strict`: every warning fails, so
   the output is a gate and not a list nobody reads. The recipe resolves the CLI through `scripts/openspec-cli.sh` at the one pinned
   release (`OPENSPEC_VERSION` in the `Justfile`; a local `openspec` at any other version is
   refused, otherwise `npx` fetches the pinned one). Without node or the CLI the recipe prints
   `SKIPPED` and exits 0 on your machine -- a skip is not a pass -- and the `spec-check` job in CI,
   which runs the same recipe, fails on the same absence:

```bash
just spec-check
```

   Changing `OPENSPEC_VERSION` is a deliberate commit: a new CLI release can add rules (1.14
   started warning on requirement bodies over 500 characters, which is how 84 warnings appeared
   at once and hid a placeholder Purpose among them).

4. Ship the spec delta in the same pull request as the code; the spec describes behaviour, the
   tests prove it.
5. On completion the change is archived to `openspec/changes/archive/<YYYY-MM-DD>-<id>/` and the
   delta is folded into the living spec. A `design.md` dies with its change; a decision that must
   outlive it becomes an ADR.

## ADRs: short, numbered, immutable

An Architecture Decision Record captures a choice a reasonable engineer could have made
differently, where the reason would otherwise be lost. `docs/adr/README.md` is the index and the
rulebook:

1. File name `docs/adr/NNNN-kebab-case-title.md`, zero-padded, never reused (the index in
   `docs/adr/README.md` lists what exists; take the next number).
2. Status moves `Proposed` → `Accepted` → `Superseded by ADR-NNNN` or `Deprecated`. An accepted
   ADR is never edited except on its status line; a changed mind is a new ADR that supersedes it.
3. Every ADR names the change that motivated it, so the context is recoverable from
   `openspec/changes/` or its archive.
4. Add a row to the index table in `docs/adr/README.md` (ADR · Title · Status · Change).
5. ADRs stay off the public site (`mkdocs.yml` excludes everything not allowlisted); a public page
   describes the behaviour and may name the ADR, never link into it. The rest of the publishing
   rule is on the [documentation page](contributor-documentation.md).
