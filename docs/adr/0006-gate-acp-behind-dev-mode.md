# ADR-0006 — Make PTY the v1 browser transport; gate ACP behind `--dev`

Status: **Accepted** (2026-08-24)

Supersedes ADR-0005's consequence that the normal browser picker exposes both
`pty` and `acp`. It does not reverse ADR-0005's retirement of the ttyd iframe.

## Context

ACP adds structured events: markdown messages, tool-call status, plans, and
permission prompts without parsing terminal escape sequences. That remains a
useful direction, but its support varies by agent and CLI version. A real Kiro
check also proved that invoking `kiro-cli acp` without the explicit StudyLoop
agent exits before the JSON-RPC handshake; `kiro-cli acp --agent study-mentor`
works. Treating ACP as an ordinary release option made a partially compatible
protocol path look as dependable as the PTY path.

The PTY/xterm.js path has one contract across the five v1-supported harnesses
(Claude Code, Codex, Gemini CLI, Kiro CLI, and OpenCode) and
now has browser gates for painting, shrink/grow resize, refresh, automatic
reattachment, stable session identity, and post-refresh input. It is the safer
v1 baseline.

## Decision

1. Normal `studyloop web` exposes **PTY only** in both session pickers.
2. `studyloop web --dev` exposes experimental ACP for capable agents as well as
   the experimental terminal renderer.
3. The boundary is server-side, not cosmetic: release-mode
   `POST /api/session/start` rejects `transport: "acp"` with HTTP 403 and tells
   the operator to restart with `--dev`.
4. ACP implementation and dogfood tests remain in the repository. Kiro launches
   ACP with the explicit `study-mentor` agent.
5. Deterministic all-harness PTY Playwright tests are required. Credentialled
   real-TUI tests are an opt-in `live_harness` lane because they depend on local
   installation/authentication and may use provider quota.
6. Grok Build remains available only under `--dev` for future compatibility
   work and is not part of the v1 support or release-test matrix.

## Consequences

- The public v1 promise is smaller and testable: one browser transport, PTY.
- `--dev` is an experimental-feature gate, not only a renderer switch.
- ACP regressions can still be found without presenting ACP as release-ready.
- A future ADR may promote ACP only after supported-agent compatibility,
  authentication, permissions, resize/refresh behaviour, and public guidance
  have their own green release gates.
