# A CLI Command

<!-- facts: F7 F11 -->

A StudyLoop command is a Click command or group in its own module under
`packages/studyloop/src/studyloop/cli/`, mounted by name in
`packages/studyloop/src/studyloop/cli/__init__.py` and imported only when invoked. Its `--help`
text is documentation that a test resolves, and its proof is a `click.testing.CliRunner` test the
coverage gate can see.

1. Put the command in `packages/studyloop/src/studyloop/cli/_<name>.py`.
2. Mount it in the `lazy_subcommands` table of `packages/studyloop/src/studyloop/cli/__init__.py`.
3. Write the `--help` text as if a learner will read only that.
4. Add a `CliRunner` test beside the nearest `packages/studyloop/tests/test_cli_*.py` file.
5. Run the three gates below before you open the pull request.

## 1. Where it lives

- One module per command or command group: `packages/studyloop/src/studyloop/cli/_*.py`. The
  leading underscore says "not imported by anyone but the mount table".
- The mount table is `lazy_subcommands` in `packages/studyloop/src/studyloop/cli/__init__.py`:
  `"chat-note": "studyloop.cli._chat_note:chat_note"` maps the name a learner types to
  `module:attribute`. `packages/studyloop/src/studyloop/cli/_lazy.py` imports the module only when
  that name is resolved, which is why `studyloop --help` stays fast with over forty commands mounted.
- Experimental commands go in the `dev_subcommands` set of the same decorator. They are absent from
  `--help` and from command resolution unless the root is invoked with `studyloop --dev`.
- Shared helpers (the rich `console`, topic lookups) come from
  `packages/studyloop/src/studyloop/cli/_shared.py`. Heavy imports belong inside the command
  function, not at module top, for the same start-up reason.

## 2. The smallest complete example

Read `packages/studyloop/src/studyloop/cli/_chat_note.py` (47 lines). It is one `@click.command`
with one argument, three options, a `click.ClickException` for the refusal path and a JSON output
flag, and it is mounted on a single line of the table. The smallest *group* is
`packages/studyloop/src/studyloop/cli/_mastery.py`: a `@click.group` with two subcommands and a
rich table. Copy the shape, not the body.

Its help text is what the learner sees, so check it by running it:

```bash
uv run studyloop --help
uv run studyloop chat-note --help
```

Every fenced `studyloop …` line on this page, on `docs/cli-reference.md` and in any `Examples:`
section of a command docstring is resolved against the real Click tree by
`packages/studyloop/tests/test_docs_drift.py` (F11). A help example that names an option the
command does not declare fails that test, so write `--help` first and let the test keep it true.

## 3. Its test

The pattern is the `CliRunner` template in the
[testing cookbook](contributor-testing.md#unit-and-cli-template-refusal-means-nothing-executed):
invoke the command object directly, assert the exit code **and** the side effect that did or did
not happen. The maintained example is
`packages/studyloop/tests/test_contributor_examples.py::test_cli_refusal_never_calls_verifier`.
For a real per-command file, read `packages/studyloop/tests/test_cli_doctor.py`: it patches the
seam the command calls (`_get_registry`) and asserts the exit-code contract for each outcome.

```bash
uv run --group dev pytest packages/studyloop/tests/test_contributor_examples.py -q
```

Name the file `packages/studyloop/tests/test_cli_<name>.py` and keep the basename unique across
`packages/studyloop/tests/` (the coverage collector imports in prepend mode).

## 4. The gate that proves it

1. The default suite runs your test: `just test` (`pyproject.toml` deselects the opt-in markers,
   F7). The focused form is the pytest line above.
2. The help text is true:

   ```bash
   uv run --group dev pytest packages/studyloop/tests/test_docs_drift.py -q -k studyloop_example
   ```

3. The command is covered. `packages/studyloop/tests/test_e2e_coverage_gate.py` discovers every
   command in the Click tree and fails if no test invokes it; skipped or xfailing tests do not
   count, and a waiver needs a written reason:

   ```bash
   uv run --group dev pytest packages/studyloop/tests/test_e2e_coverage_gate.py -q -k cli
   ```

`just preflight` runs all of these with lint, types, JS tests and the strict docs build (F7).

## 5. What reviewers look for

- The name in `lazy_subcommands` is what a learner would type; the module imports nothing heavy at
  top level, and nothing in `packages/studyloop/src/studyloop/cli/__init__.py` imports your module.
- `--help` says what the command does in one sentence; every option has `help=`; refusals are a
  `click.ClickException` with a remedy, never a traceback.
- The test asserts the exit code and the side effect (one record written, nothing executed), as
  the cookbook template does, and it fails without your change.
- A learner-facing command has its row in `docs/cli-reference.md`; a developer-only command is in
  `dev_subcommands`, not hidden behind an environment variable.
- The changelog entry under `[Unreleased]` names the behaviour, not the file
  (see [the changelog process](contributor-changelog.md)).
