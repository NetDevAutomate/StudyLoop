# Architecture Decision Records

Short, immutable records of decisions that were *not* obvious — where a
reasonable engineer could have chosen differently, and where the reason
would otherwise be lost.

## Relationship to OpenSpec

| Artefact | Answers | Lifecycle |
|---|---|---|
| `openspec/specs/<cap>/spec.md` | What the system does, normatively | Living — updated on archive |
| `openspec/changes/<change>/design.md` | How this change is built | Archived with the change |
| `docs/adr/NNNN-*.md` | Why we chose X over Y | **Immutable** — superseded, never edited |

A `design.md` dies with its change. An ADR outlives it. When a design
decision will still be load-bearing in six months — when someone will read
the code and ask "why on earth is it done this way?" — it gets an ADR, and
`design.md` links to it rather than restating it.

## Conventions

- Filename: `NNNN-kebab-case-title.md`, zero-padded, never reused.
- Status: `Proposed` → `Accepted` → (`Superseded by ADR-NNNN` | `Deprecated`).
- An accepted ADR is **never edited** except to change its status line. A
  changed mind means a new ADR that supersedes it.
- Every ADR names the change that motivated it, so the full context is
  recoverable from `openspec/changes/` (or its archive).

## Index

| ADR | Title | Status | Change |
|---|---|---|---|
| [0001](0001-body-double-reuses-session-start-endpoint.md) | Body Double reuses `POST /api/session/start` | Accepted | `body-double-own-agent-picker` |
| [0002](0002-origin-scoped-live-agent-console.md) | Origin-scoped addressing for `liveAgentConsole()` | Accepted | `body-double-own-agent-picker` |
| [0003](0003-body-double-exempt-from-park-first-friction.md) | Body Double is exempt from park-first friction | Accepted | `body-double-own-agent-picker` |
| [0004](0004-retire-terminal-panel-from-body-double.md) | Unmount `terminalPanel()` without deleting it | Superseded by ADR-0008 | `body-double-own-agent-picker` |
| [0005](0005-retire-ttyd-browser-surface.md) | Retire the ttyd browser surface, keep the server transport | Superseded in part by ADR-0008 | `live-agent-console.js`, `index.html` |
| [0006](0006-bridge-aware-deferred-topics.md) | Bridge-aware deferred topics, behind a testable 0.1.0 boundary | Proposed | `reviews/0.1.0-SCOPE-DECISION.md` |
| [0007](0007-dev-only-vendored-assets.md) | Dev-only vendored assets live in git, not in the wheel | Accepted | `vendor/dev/` |
| [0008](0008-retire-ttyd-entirely.md) | Retire ttyd entirely; the Web UI owns interactive sessions | Accepted | ttyd retirement stages 2-7 |
| [0009](0009-one-session-authority.md) | The session-state file is the claim; the in-process slot is a cache | Accepted | M2 session-authority remediation |
| [0010](0010-second-brains-are-projections.md) | Second brains are projections; plan Markdown is the source of truth | Accepted | `second-brain` |
| [0011](0011-retire-okf-ontology-and-concept-sidecar.md) | Retire the OKF import, the tier-1 ontology and the concept sidecar — no functional remnant | Accepted | 2026-09-10 OKF removal (Stages 4–6) |
| [0012](0012-practice-check-delivery.md) | Delivering a `practice_check` result to the live mentor — PTY framing, ACP serialisation, size bound, learner-visible failure | Proposed | `module-contract-v1` (T1 spike, for council M0) |
| [0013](0013-repo-root-agents-md-is-the-contributor-file.md) | The repo-root `AGENTS.md` is the contributor file; the installer never links into the checkout | Accepted | 2026-10-22 council pass 3, ruling D1 (`309074c7`) |
| [0014](0014-launcher-token-gates-the-dashboard-cookie.md) | The dashboard cookie is issued only to a browser presenting the launcher's sign-in token; artefacts and loopback origins sit inside the same boundary | Accepted | 2026-10-22 council pass 3, rulings D2, D9.1, D9.2 (lane E, merge `c10c5096`) |
| [0015](0015-pi-mentor-sessions-load-only-the-export-extension.md) | pi mentor sessions load StudyLoop's export extension and no other | Accepted | 2026-10-22 council pass 3, ruling D3 (`bd3557e9`) |
| [0016](0016-deprecate-session-maint-archive.md) | `session-maint archive` is deprecated for `sync-full` + `prune`, not rebuilt | Accepted | 2026-10-22 council pass 3, ruling D4 (`4485f5e5`) |
| [0017](0017-delete-keeps-learner-record-sessions-unless-forgotten.md) | Age-based `delete` keeps sessions that own learner records; `--forget-learner-records` destroys them through the tombstone path | Accepted | 2026-10-22 council pass 3, ruling D5 (`1f171b62`) |
| [0018](0018-trufflehog-scans-each-pull-request-range.md) | trufflehog in CI scans each pull request's own range, pinned and fail-closed | Accepted | 2026-10-22 council pass 3, ruling D6 (`a5a17045`, `8965206d`) |
| [0019](0019-bind-address-replaces-lan.md) | `--bind <ip>` replaces `--lan`; second-device access goes over a tunnel or a VPN address | Accepted | 2026-10-22 council pass 3, ruling D7, 3–2 (`db30f9ca`) |
| [0020](0020-log-topic-partial-result.md) | `log_topic` reports a failed spaced-repetition write as a typed partial result, not an error | Accepted | 2026-10-22 council pass 3, ruling D9.3 (`12f53ab2`) |
| [0021](0021-experiments-evidence-context-leaves-main.md) | `experiments/evidence_context` leaves `main` for an archive branch | Accepted | 2026-10-22 owner decision on council pass 3 question D8; archive refs withdrawn 2026-10-23 (amendment), tree preserved at `6c9571c8` on `main` |
