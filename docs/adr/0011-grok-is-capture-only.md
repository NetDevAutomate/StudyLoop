# ADR-0011 — Grok is a capture-only source, not an installable mentor harness

**Status:** Proposed, 2026-09-06 (→ Accepted when the user commits Phase 0).
Motivated by ARBITRATION.md 2026-09-06: "Grok is in … the reversal should
be a commit with a reason, not an accident." Change:
`stabilise-session-memory-release`.

## Context

main removed Grok support by an earlier decision; worktrees A and B
re-added it as `session-export --grok-only` (`exporters/grok.py`) and it
captures daily. Grok has never had skill/hook installer support, unlike
Claude Code, Codex, Kiro, OpenCode and pi, and the changelog already
describes it as "separate from … automatic-hook integrations". Two axes —
capture source and installable harness — looked like one inconsistent
on/off decision.

## Decision

Grok stays **in** as a capture-only exporter and stays **out** of
`RELEASE_HARNESSES` and every installer/hook path. Adding harness-level
Grok support is a new feature requiring its own openspec change (Phase 2+
at the earliest), not a bug against this ADR. Reconciliation of main must
never drop `grok.py`/`test_exporter_grok.py`.

## Consequences

The exporter list is six modules; docs and the `session-export` spec name
Grok explicitly and describe hook support separately. No installer change.
