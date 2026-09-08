# ADR-0011 — Grok is a capture-only source, not an installable mentor harness

**Status:** Accepted, 2026-09-08. Motivated by the 2026-09-06 Phase 0
arbitration: “Grok is in … the reversal should be a commit with a reason,
not an accident.” Change: `sessionweaver-phase2-retrofit`.

## Context

The production lineage re-added Grok as `session-export --grok-only`, and it
captures local transcripts. Grok has never had skill or lifecycle-hook
installer support, unlike Claude Code, Codex, Kiro, OpenCode, and pi. The
capture-source and installable-harness axes had been presented as one
inconsistent on/off decision.

## Decision

Grok stays **in** as a capture-only exporter and stays **out** of
`RELEASE_HARNESSES` and every installer/hook path. Adding harness-level Grok
support is a new feature requiring its own OpenSpec change, not a bug against
this ADR. Reconciliation must never drop `grok.py` or its exporter tests.

## Consequences

The exporter list is six modules. Documentation and the `session-export` spec
name Grok explicitly and describe automatic-hook support separately. No Grok
mentor adapter or hook installer is implied.
