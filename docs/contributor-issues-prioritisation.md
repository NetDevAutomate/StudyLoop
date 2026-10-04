# Issues and Prioritisation
<!-- facts: F2 F3 F10 -->

Open an issue at [github.com/NetDevAutomate/StudyLoop/issues](https://github.com/NetDevAutomate/StudyLoop/issues).
For a bug, attach the four things in the next section with the private paths removed; for a change,
answer the three questions under *Propose a change*. Maintainers read every issue in the fixed order
at the end of this page.

## Report a bug

1. **What you were trying to do**, then the exact command or Web UI action, as typed or clicked.
2. **What happened and what you expected**, in two sentences, with the exact error text if there was one.
3. **Your version and the doctor report**, redacted. Run both from the repository root and paste the
   output into a fenced block:

    ```bash
    uv run studyloop --version
    uv run studyloop doctor --json | sed "s|$HOME|~|g"
    ```

4. **Whether it reproduces with Kiro CLI**, the documented demo harness, and if not which harness you used.

The doctor's exit code is part of the report: `0` means every check passed, `1` means a check failed or
a warning is auto-fixable (`--fix` applies the safe fixes), `2` means a core check failed and cannot be
fixed automatically. Say which one you saw.

Never paste API keys, bearer tokens, session transcripts, or your full local configuration into an
issue, fixture, screenshot or log. Session content is the learner's private material, even your own.

## Redact before you paste

The `sed` above replaces your home directory with `~` everywhere in the JSON, so a message such as
`Config valid: /Users/you/.config/studyloop/config.yaml` becomes `Config valid: ~/.config/studyloop/config.yaml`.
It does not remove anything else. Before you paste, read the output once and delete:

1. Review-directory and vault names you do not want public (the `review_dir_*` and `obsidian_*`
   checks print them in full).
2. Any `fix_hint` that quotes a local path or a value from your `config.yaml`.
3. Anything that names another person, a course you are not allowed to share, or an account.

If the redacted report is still too revealing, say so and offer to send it to the maintainer
privately; an issue with no doctor output is better than one with a leaked key.

## Propose a change

Describe the learner situation first, then the smallest change that would help, then why a core
change rather than something a user can already configure. Three questions, in order:

1. **Who is the learner and what were they doing** — energy level, the task, where the friction was.
2. **What is the smallest change that removes the friction** — one behaviour, not a feature list. The
   [AuDHD learning philosophy](audhd-learning-philosophy.md) explains why "smaller" wins.
3. **What does it cost** — a new option to document, a schema change, a new external tool, a change to
   what the mentor sees.

A behaviour or design change gets an issue first and then an OpenSpec proposal under
`openspec/changes/`; a small fix can go straight to a pull request. The rules, including the one that
matters most here, are in [Making changes](contributing.md#making-changes): a **new mentor harness or
backend is declined** unless the issue defines the persona mechanism, launch and resume commands,
session store, exporter, health check, failure behaviour and a live acceptance path. A proposal for a
practice module follows the template on the [modules proposal page](contributor-modules.md).

## Lifecycle

1. You open the issue with the attachments above. The maintainer reads every new issue; there is no
   response-time promise yet, and a clear reproduction moves an issue up.
2. The maintainer asks for what is missing, or confirms the bug, or declines the change and says why.
3. A fix or a change lands as a pull request that references the issue, with a test that fails on
   revert and a changelog entry in the learner's terms; see
   [Raising a pull request](contributor-pull-requests.md) for the five questions its description answers.
4. The issue closes when that pull request merges. Reopen it, with the new evidence, if the behaviour returns.

## How maintainers prioritise

1. Anything that breaks or endangers a learner's session, data or privacy.
2. Friction in the first week: setup, first session, first review.
3. Truth of the documentation.
4. Accessibility and low-energy paths.
5. New capability, in the order the roadmap gives.

Clear reproductions move an issue up; the four attachments under *Report a bug* are what make a
reproduction clear.
