# Stage22: what did the source actually establish?

The canonical store now receives native records from the real Codex, Claude Code,
Kiro CLI and Grok exporters. This adds tool results and execution envelopes that
the legacy conversation view omitted. The improvement measured here is capture
coverage and provenance preservation. Answer accuracy has not been measured in
this stage, and the full production goal remains active.

## Run the lesson

From the experimental worktree root, choose a fresh output directory:

```sh
uv run python -m experiments.evidence_context.native_capture.runner --output /tmp/evidence-stage-22
open /tmp/evidence-stage-22/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_native_capture.py experiments/evidence_context/tests/test_native_capture_lesson.py -q
uv run session-context health --db /tmp/evidence-stage-22/sessions.db
```

The runner creates fictional archives for all four harnesses, a fresh database,
and an isolated child-process configuration. No model calls or owner database
access are involved. Five expandable views explain the captured labels, legacy
projection, unchanged replay, malformed source and capture health. Preserve the
checkpoint in [STAGES.md](../STAGES.md) to run this exact version later.

The optional real-data probe deliberately reads local archives. It selects at
most two recent stable StudyLoop/MailGraph sessions per harness by default, with
a 32MiB ceiling per JSONL file. It imports into a temporary database, then deletes
that temporary directory after writing an aggregate report. It never exports
transcript bodies to the report or a model gateway:

```sh
uv run python -m experiments.evidence_context.native_capture.audit_local --limit 2 --output /tmp/stage22-local-audit.json
```

This selection is narrow and not representative. It does not enumerate every
possible source format or prove every session was captured. Kiro's optional probe
currently requires its `conversations_v2` table; the actual exporter supports its
older table too. Source archives are read-only; application configuration and the
owner's sessions database remain unchanged.

## The key distinction

Consider three records containing essentially the same wording:

| Native record | Code-owned origin | What it establishes |
|---|---|---|
| Assistant text: “all tests passed” | `conversation_message` | Someone reported this claim |
| Generic tool output: “process exited with code 0” | `tool_result` | The archive recorded this tool result; its prose does not supply typed exit metadata |
| Codex `CommandExecution`, terminal status, integer exit code | `process_exit` | The archive recorded a completed process and its exit code |

The third is stronger execution evidence. It still cannot prove the tested
revision, applicability to the present question, or that the command actually
checked the intended behaviour. These are local archive receipts, not signed
remote attestations. A native file can itself be edited; the captured hash protects
the stored version's identity, not the authenticity of the original machine.

In networking terms, receiving a device's structured interface-status record is
different from reading a ticket that says “the link is fixed.” Neither proves
that the complete application path works. The record's scope determines the
claim it can support.

## Why the adapters intentionally differ

Codex's inspected desktop archives contain typed `CommandExecution` events.
Only `completed` or `failed` with a real Python integer qualifies. A string `"0"`,
a Boolean, a missing code, or an unrecognised terminal state stays `tool_result`.
Negative integer exit codes are retained without inventing a signal explanation.

Claude's tool results can live inside a message whose outer role is `user`.
Calling that entire message user conversation would misclassify the tool output.
The adapter reads each typed content block independently. Grok's tool-result
records and Kiro's `ToolUseResults`/`CancelledToolUses` are retained as results.
Kiro's `Success` is not converted into process exit zero. None of these adapters
extracts authority from a success phrase in the body.

Invocations are retained with origin `unknown`: issuing a command does not prove
it returned. Known reasoning/system/environment envelopes and recognized media
blocks are excluded. Arbitrary text is not parsed as an embedded envelope; quoted
JSON remains quoted text. This is format-aware collection, not a general secrets
scrubber or a guarantee that arbitrary text contains no encoded media.

Session-start Git metadata is not copied onto later commands. A session can edit
files or change branches after it starts. The source machine also stays unknown
where the archive does not establish it. A separate capture receipt records the
importing machine; this is not necessarily where the session originally ran.

## Why SQLite still serves this increment

No new database is needed to retain these relationships. Native evidence remains
in `context_evidence`; v34 adds `context_native_message_sources` and
`context_capture_runs`. Foreign keys connect the legacy rendering to its native
inputs, and immutable evidence versions preserve earlier bytes.

The rendering link records a hash of the rendered legacy body. It means
**rendered from**, not **this passage supports the claim**. Those are different
relationships with different proof requirements. Stage21's legacy input capture
remains conservatively `unknown`; this stage does not silently promote an old
assessment because a new native link is now available.

Keeping both views in one transaction is useful: legacy rows, native evidence and
rendering links commit together. Injecting a failure after one evidence insert
proves that none of the batch leaks through. A graph engine could store edges,
but would not by itself solve parser authority, atomic cross-store writes or
validation applicability. This stage supplies no reason to add that operational
complexity.

An export attempt has a separate durable receipt. It starts before batch work, so
an interrupted process leaves evidence that an attempt began. On interruption,
pending writes now roll back even if the connection is later reused. Earlier
committed batches can remain; the receipt must not label the whole attempt complete.
The receipt's statistics are exporter-reported counters, not an exact inventory
of unique failed archives. A lost database connection can prevent a final receipt;
the missing finish therefore remains inconclusive.

## Replay, scope and forgetting

Parser fingerprint versions change with this import format. An unchanged archive
captured by the older parser is reprocessed once. The tests exercise this with
each actual exporter; Kiro historically stores its fingerprint in session
metadata, while the other three use the common fingerprint column.

Repeated capture deduplicates identical native versions. Modified source bytes
produce another immutable version. Native histories can compact, so absence from
the current file does not automatically erase previously captured evidence.

Already applied project-root policy assigns newly captured sessions. Explicit or
synced ownership wins over root inference. An approved root assignment follows
a changed source path; unapplied configuration drift is never implicitly approved.
These are explicit project rules, never deductions from the harness name.

Tombstoned sessions are filtered inside the batch transaction and counted as
retired. They cannot be reimported, and their presence does not block unrelated
sessions in the batch. This proves local replay resistance, not complete forgetting
through every replica, backup, restore or derived store. That remains a shipping
requirement in [delivery/GOAL.md](../delivery/GOAL.md).

## Measured local results

The 2026-09-06 probe imported eight selected sessions with no errors:

| Harness | Sessions | Conversation blocks | Tool results | Process exits | Invocations (`unknown`) |
|---|---:|---:|---:|---:|---:|
| Codex | 2 | 69 | 235 | 162 | 235 |
| Claude Code | 2 | 119 | 324 | 0 | 324 |
| Kiro CLI | 2 | 11 | 45 | 0 | 45 |
| Grok | 2 | 61 | 268 | 0 | 0 |

Total: **1,898 native records**, alongside **577 legacy messages**. These units
differ: legacy messages can flatten multiple blocks and tool markers, while native
records separate them. The result is not “3.3 times better answers.” The more
useful signal is **872 retained tool results and 162 typed process-exit records**
that richer retrieval can inspect.

All 1,898 body hashes matched their stored bodies. Both sampled Codex archives
declare `originator: Codex Desktop`, version `0.153.0`. Their source files remained
unchanged through the probe. Import timings were 0.121s Codex, 0.222s Claude,
0.078s Grok and 0.029s Kiro. These tiny samples do not establish full-backfill
latency, memory usage or query scaling. Every record's revision and original
machine remained unknown; no applicability was manufactured.

The tests finished with 1,237 session-tools passes, 255 experiment passes and one
optional dependency skip, plus 45 StudyLoop consumer/extractor/CLI-contract
compatibility passes. The browser showed five sections, working data expansion,
no horizontal overflow and no console errors. This is a tested local increment,
not installed-hook or release acceptance.

## What to learn next

Capture now supplies the native material. The product still needs bounded,
scoped retrieval that distinguishes source provenance, exact support and decision
sufficiency, plus complete learner-state ownership and source lifecycle across
sync/restore. The council arbitration is recorded separately so its claims can
also be checked against the evidence.
