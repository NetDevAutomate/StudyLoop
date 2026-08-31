# Contributing to StudyLoop

StudyLoop welcomes code and non-code contributions. A confusing setup step, an
accessibility observation, a clearer screenshot, or a precise account of where
a study flow became overwhelming can be as valuable as a feature.

## Good first contributions

- Report a reproducible learner-facing problem.
- Improve plain-language setup or troubleshooting guidance.
- Check a workflow with a different screen size, energy level, or assistive
  technology.
- Add a focused regression test for an existing bug.
- Improve one of the five supported harnesses: Kiro CLI, Codex, Claude Code,
  OpenCode, or pi.

The current pre-release deliberately does not claim every coding assistant.
Proposals for another harness should begin with an issue describing its session
format, persona mechanism, start/resume behavior, export path, and live proof.

## Before opening an issue

For a bug, include:

1. what you were trying to do;
2. the exact command or Web UI action;
3. what happened and what you expected;
4. the output of `studyloop doctor --json`, with private paths or credentials
   removed;
5. whether the problem reproduces with Kiro, the documented demo harness.

Never paste API keys, bearer tokens, session transcripts, or your full local
configuration into an issue.

## Make a local change

```bash
git clone https://github.com/NetDevAutomate/StudyLoop.git studyloop
cd studyloop
uv sync --all-packages --all-extras
uv run playwright install chromium
```

Create a focused branch, make the smallest coherent change, and add a test at
the nearest useful boundary. Tests may use isolated fixtures, but product,
demo, release-note, and acceptance evidence must come from live behavior and
must never present placeholder data as real learner data.

## Validate before a pull request

```bash
just release-check
just docs
```

The release check calculates its own current test results. Do not copy a test
total into documentation or release notes; those numbers become stale as soon
as the suite changes.

If your change affects a live mentor session, also record the specific manual
journey you checked. Automated green and manual acceptance are separate claims.

## Pull request shape

Keep the description short and evidence-led:

- What learner or contributor problem does this solve?
- What changed?
- What automated checks passed?
- What live or manual journey was checked?
- What remains unverified?

Small pull requests are easier to review and safer to reverse. If the change
touches public behavior and internal architecture, consider splitting the work
unless both pieces are required for one complete outcome.

## Documentation boundaries

The published site is an explicit allowlist in `mkdocs.yml`. New repository
notes, audits, plans, evidence, handoffs, and architecture investigations stay
internal unless they are deliberately rewritten for learners and added to that
allowlist. This prevents implementation history from becoming accidental
product documentation.

For the full development workflow and code conventions, read the repository's
[CONTRIBUTING.md](https://github.com/NetDevAutomate/StudyLoop/blob/main/CONTRIBUTING.md).
