# Council arbitration: provenance ownership

Two separate reviews informed this checkpoint. Private original requests/responses
are retained under `.private/delivery/design-council` and
`.private/stage-17/fresh-council`. Both returned structured responses from Fable 5.1,
Grok 4.6, Qwen3-Coder and Mistral Large 3. A valid response is not necessarily a
correct review. No majority vote certifies the design.

## Production boundary review

The council favored additive canonical SQLite records, separate interpretations,
explicit scope and tombstone propagation. Fable specifically identified legacy
MCP reads and sync as bypasses that must be addressed before installers. Inspection
confirms those concerns. Installer ownership belongs in the independently packaged
memory component, with StudyLoop delegating.

Qwen's suggestion of a limited production pilot is premature: the required scope,
source and lifecycle protections do not yet exist on production paths. Grok's summary
conflated six model-origin errors with accepted semantic errors; Stage16 source checks
blocked those live origin errors, while two control interpretations remained wrong.
A request for down-migration also does not match the forward-only migration framework;
rollback must be rehearsed with a consistent backup and active forgetting metadata.

## Fresh-case review before execution

Fable and Grok supplied useful per-case source/proposal distinctions. All proposal
meanings remain unverified; only the three process-exit fixtures establish captured
command completion. A generic tool result is observed output, with unknown execution
state. These are separate dimensions, not a contradiction.

Their objection to `completed` alone identifies a real presentation risk. I retained
completion as process lifecycle state and added the captured exit code beside it.
That preserves the distinction between a command ending, how it ended, and whether
it validated the intended behavior. We did not redefine a failed process as still
running. Existing production unit controls also cover missing/string/bool exit status,
negative return code and missing invocation target.

Qwen and Mistral included demonstrable misreadings: the brief explicitly prohibited
scope inference and proposal override, while their responses criticized it for allowing
both. Mistral listed exit-zero-implies-validation as an assumption despite the brief
stating the opposite. I rejected those premises. Their general caution about trusted
importer assumptions is valid and remains part of production acceptance.

## Decision

Proceed with the code-owned provenance contract and preserve the original proposals.
Do not promote the legacy narrative renderer into production. Replay improves eligible
coverage but retains two semantic false releases. Fresh fixtures expose unknown execution
and unverified interpretation explicitly; they do not prove semantic understanding.

This checkpoint has four-provider design and pre-execution boundary review. It does
not claim four-provider agreement on every case, independent human labels, a fresh
model answer trial or production release approval. Result and implementation review
continues against the production components as they become concrete.
