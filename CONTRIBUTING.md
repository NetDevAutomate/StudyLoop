# Contributing to StudyLoop

Thank you for helping improve an AuDHD-aware learning tool. The full contributor guide lives in the
documentation: **[docs/contributing.md](docs/contributing.md)** (published at
<https://netdevautomate.github.io/StudyLoop/contributing/>). It covers the development environment,
repository layout, how changes are made and tested, CI, documentation standards, the changelog, pull
requests, issues, prioritisation, AI usage and models through a LiteLLM gateway, and security.

The short version:

```bash
git clone https://github.com/NetDevAutomate/StudyLoop.git studyloop
cd studyloop
uv sync --all-packages --all-extras
uv run playwright install chromium
uv run pre-commit install
just preflight
```

- Branch from `main` with a `feat/`, `fix/`, `docs/` or `test/` prefix; never `lane/`.
- Tests first; docs and changelog in the same change; `just preflight` green before you push.
- Never include credentials, session transcripts, personal hostnames or unredacted local configuration in
  issues, fixtures, screenshots or logs.
- Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1).
- Security concerns go through [GitHub's private advisory form](https://github.com/NetDevAutomate/StudyLoop/security/advisories/new), never a public issue.

StudyLoop is a 0.1.x pre-release with five first-party mentor harnesses (Kiro CLI, Codex and Claude Code are
core; OpenCode and pi are preview). Proposals for another harness start with an issue, not a pull request.
