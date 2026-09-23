# S1-0 — Capability lock (learning tier, item 1)

**Date:** 2026-09-23 · **Tree:** `main` @ `c1a28de1` (decisions recorded on PR #36, head `046fa499`) ·
**Issue:** #38 · **Plan:** `docs/architecture/learning-tier/plan-2026-09-19.md` §3 S1-0 · **Branch:** `feat/learning-tier-fed`

This receipt records, from source, how each of the six supported harnesses grants tool use to the
mentor today, and freezes the two writer sets item 1 builds against. It is the S1-0 finish line:
nothing here is a change; S1-RED and S1-GREEN cite it instead of re-deriving it. Every claim carries
the file and line it was read from on the tree above.

## 1. Writer sets (frozen)

| Set | Tools | Character | Rule this branch (owner decision 2, plan §7) |
|---|---|---|---|
| `W_auto` | `log_topic` (`mcp/tools.py:583`), `log_struggle` (`:850`), `record_plan_learning` (`:131`), **`record_teachback` (new — no MCP tool exists; the CLI writer is `history/teachback.py:27`)** | Additive: each appends a record the learner agreed to or stated | **Named in every harness definition; prompt-per-call everywhere; no new pre-approval on any harness.** |
| `W_srs` | `record_study_progress` (`mcp/tools.py:114`), `record_topic_progress` (`:538`), `log_review_outcome` (`:648`) | SRS mutators: reschedule a card or resolve a topic on an id nothing verifies (`card_hash`, backlog `topic_id`) | Prompt-per-call, unchanged, not named by any trigger. |

Readers the definitions already name (`get_concept_context`, `get_study_history`, `get_next_action`,
`get_topic_suggestions`, `get_active_topics`, `read_lesson`, …) are outside both sets and unchanged.

## 2. Grant mechanism per harness (as it is)

| Harness | Definition file(s) | Grant grammar in repo | Approval cell today | S1-GREEN changes (instruction only) |
|---|---|---|---|---|
| **Kiro CLI** | `agents/kiro/study-mentor.json`; persona `agents/kiro/study-mentor/persona.md` | `tools` (`:13`) exposes `@builtin @study-speak @session-db @studyloop`; `allowedTools` (`:50-68`) pre-approves `execute_bash` (`:52`), five `@studyloop/get_*` readers (`:63-67`) and one writer, `@studyloop/log_topic` (`:68`) | `log_topic` pre-approved; the other three `W_auto` tools prompt; **CLI writers (`studyloop progress`, `studyloop teachback`) run un-prompted through `execute_bash`** | Persona repointed (`persona.md:32` and `:81` route "record progress" to `uv run tutor-checkpoint`, a different tool); trigger table projected. `allowedTools` **unchanged** — `log_topic` stays as the one recorded asymmetry. |
| **Claude Code** | `agents/claude/socratic-mentor.md`; `agents/claude/settings.json` | Sub-agent frontmatter `tools:` (`socratic-mentor.md:5`) = `Read, Write, Grep, Bash` — **no `mcp__studyloop__*` tool named**; `settings.json` has a single key, `statusLine` — **no `permissions` block**. The sibling `study-plan-architect.md:5` shows the naming grammar (ten `mcp__studyloop__*` tools). | Every tool call prompts; the mentor cannot call any `studyloop` MCP tool at all because none is named — it reaches the learning tier only through `Bash` and the CLI | `tools:` line names each `W_auto` tool and the readers (naming is instruction, not approval). **No `permissions` block is added.** |
| **OpenCode** | `agents/opencode/study-mentor.md` | `permission:` (`:10-16`): `edit: allow`; `bash:` `"studyloop *": allow`, `"session-* *": allow`, `"uv run tutor-*": allow`, `"*": ask` | CLI writers un-prompted through the bash wildcard (wider than least privilege — every `studyloop` verb); MCP tool approval is the harness default | Persona names each `W_auto` tool; **wildcard unchanged** (recorded here as known, not least-privilege, out of scope for this branch). |
| **Codex** | `agents/codex/AGENTS.md` (canonical persona, written into the session dir by `adapters/codex.py:20-27`) | **None in repo.** Codex reads `AGENTS.md` from cwd; approval is Codex's own policy | Harness-side | Canonical persona names each `W_auto` tool via the shared protocol; nothing else. |
| **pi** | `agents/pi/AGENTS.md` (+ `agents/pi/extensions/studyloop-session-export.ts`); written by `adapters/pi.py:15-16` | **None in repo.** | Harness-side | As Codex. |
| **Grok Build** | no `agents/grok/` directory (by design — `adapters/grok.py:97-101` writes `AGENTS.md` into the session dir; `:17` records that no Grok permission — `ui.yolo`, tool approval, hooks trust — is touched) | **None in repo.** | Harness-side | As Codex. No `agents/grok/` is created. |

Parity, therefore, is of the **instruction** — one canonical `agents/shared/recording-protocol.md` with a
fenced YAML trigger table, projected byte-identically into every definition above and hashed in
`agents/manifest.json` — and of the **names**: every definition names the same `W_auto` set. It is never
parity of approval: three of the six harnesses cannot express approval in this repository at all.

## 3. The writer that does not exist yet — its contract, read from the CLI

`record_teachback` (MCP) must validate exactly as `cli/_teachback.py` does and land through the same
function:

- Scores: exactly five integers, each 1–4 (`cli/_teachback.py:16-46`), in the order
  `(accuracy, own_words, structure, depth, transfer)` (`history/teachback.py:27-42` docstring).
- `review_type` ∈ `TEACHBACK_TYPES = ("micro", "structured", "transfer", "full")` (`cli/_teachback.py:12`).
- `angle` and `notes` optional strings.
- Writer: `history.teachback.record_teachback(concept, topic, scores, review_type, angle, notes,
  session_id) -> bool`; one row in `teach_back_scores`, whose five score columns carry
  `CHECK(... BETWEEN 1 AND 4)` (`agent_session_tools/migrations.py:504-513`); `False` means no
  connection, and the MCP tool must surface that as a `ToolError`, not a silent success.
- `session_id` is bound from the live session state, the way `end_session` reads it
  (`mcp/tools.py:529-531`, `read_session_state()["study_session_id"]`), never from the caller.
- Teach-backs are events: a repeated call is two rows, documented as such (plan §5).

## 4. What is *not* in this receipt, on purpose

- No grant is widened or narrowed. The only edits S1-GREEN makes to definition files are names and the
  projected protocol.
- The noticing episode (decision 3) is scheduled by rule — the first real study session after S1-GREEN
  reaches `main` — and its date is written into the S1-SIM receipt, not here.
- Item 2 (Jev) is not on this branch (decision 1; #39).

**S1-0 finish:** this file committed. Next: S1-RED (plan §5 table) — `test_mcp_teachback.py` (tool
absent), `test_adapter_parity.py` extended (names absent, no new grants),
`test_docs_harness_tier_contract.py` extended (protocol absent; `persona.md:32` still names
`tutor-checkpoint`), `test_writer_isolation.py` (guard if it already passes), no-trigger/duplicate replay.
