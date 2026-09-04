## Why

StudyLoop has no "where does today's studying sit in my day" surface. Learners
already keep a second brain — an Obsidian vault, xTiles, a notebook — and
StudyLoop already writes agent-session memory into a vault (`AgentMemory/`), but
study plans, the next action and due reviews exist only inside StudyLoop. To see
them beside everything else in a day, a learner has to retype them.

Three constraints shape the answer:

1. **A free, local option must exist.** Obsidian is plain Markdown on disk, so
   it needs no credential and no network. Any paid provider is additive.
2. **It must be invisible until chosen.** Most learners will never configure a
   second brain. An unconfigured feature that still imports a module, prints an
   offer or asks a wizard question is a regression for them.
3. **There can be only one writer of a plan.** The plan Markdown is what the
   agent reads and what `studyloop plan …` edits. A note system that can also
   write it creates a second writer the agent cannot see.

## What Changes

- **An optional `second_brain:` config section**, default `provider: none`,
  parsed into `SecondBrainConfig`. No environment variable selects a provider.
- **A `SecondBrain` protocol** — runtime-checkable, exactly six methods
  (`describe`, `is_available`, `publish_plan`, `publish_today`,
  `publish_learning_record`, `pull_notes`) — with a `NullBackend` returned
  whenever no provider is configured, and provider modules imported only inside
  the factory.
- **An Obsidian backend** writing projections into `<vault>/<folder>/`
  (`Study/Plans/<plan_id>.md`, `Study/Today.md`): atomic, idempotent, refusing
  any target outside the vault or lacking StudyLoop's `studyloop:` frontmatter
  marker. Plain files and nothing else: an official-Obsidian-CLI adapter was
  built and withdrawn before release (design D4), and the four config keys it
  used (`use_cli`, `vault_name`, `template`, `daily_note`) are refused with an
  error naming them rather than silently ignored (design D12).
- **A `studyloop brain` command group** — `status`, `publish`, `pull`, `enable`,
  `template` — lazily registered, each with `--json`.
- **A once-only wind-down offer**: the protocol offers a publish exactly once,
  and only when a configured provider supports publishing.
- **xTiles stage 1**: `provider: xtiles` is accepted, reports "configured, no
  programmatic backend", and is served by docs, prompts and an opt-in assistant
  skill rather than a client.

## Capabilities

### New Capabilities

- `second-brain`: the `SecondBrain` protocol and its backends, the projection
  contract (ownership marker, vault boundary, atomic idempotent writes), the
  explicit read-only pull, and the wind-down offer
  gate.

### Modified Capabilities

- `configuration-and-secrets`: gains the optional `second_brain` section and its
  one-line validation errors; the key counts as known for the unknown-key
  report.
- `cli-surface`: gains the lazily registered `brain` group, with `--json` on
  every command and no backend import at `--help` time.

## Impact

- `packages/studyloop/src/studyloop/second_brain/` — NEW: `core`, `factory`,
  `obsidian`, `obsidian_writer`, `projection`, `backlinks`, `templates`.
- `packages/studyloop/src/studyloop/cli/_brain.py` — NEW: the `brain` group.
- `packages/studyloop/src/studyloop/cli/__init__.py` — one lazy registration.
- `packages/studyloop/src/studyloop/settings.py` — the `second_brain` section.
- `packages/studyloop/src/studyloop/doctor/config.py` — a second-brain check.
- `packages/studyloop/src/studyloop/planning/markdown.py` — heading constants
  the projection renderer reads instead of re-deriving.
- `packages/studyloop/src/studyloop/data/templates/obsidian/` — NEW: templates
  shipped as package data.
- `agents/shared/wind-down-protocol.md` — the gated, once-only offer.
- `docs/adr/0010-second-brains-are-projections.md`,
  `docs/architecture/second-brain.md` — the decision and its contract.
- No change to session transports, the web UI, or the MCP publish surface.

## Non-Goals

- Two-way synchronisation, or any path that writes the plan Markdown from a
  note system.
- A programmatic xTiles API client (stage 2 at the earliest, and only against a
  documented, versioned API).
- A web-UI "send to second brain" control.
- An MCP publish tool.
- Depending on, or shipping, third-party Obsidian MCP servers.

## Risks / Trade-offs

- **Writes into a learner's real files.** Mitigated by the ownership marker, the
  vault-boundary refusal, atomic replace, and a test suite that cannot resolve
  the real vault at all.
- **The Obsidian CLI grammar is unversioned.** Resolved by withdrawal: the
  opt-in adapter was built, reviewed and removed before release (design D4);
  plain files carry the whole feature, and its four config keys are refused
  with an error naming them.
- **A learner edits a projection and loses the edit.** Accepted and documented:
  edits are replaced on the next publish with a warning, and personal notes
  belong in the sibling `.notes.md` file that StudyLoop only ever reads.
- **Feature creep into "sync".** Held off by ADR-0010 and by the contract test
  that asserts the plan bytes are unchanged after every backend operation.

## Migration Plan

None. The feature is inert until `second_brain.provider` is set, so existing
installations see no change: no new file, no new prompt, no new import. Enabling
it is a config edit (or `studyloop brain enable`); disabling it is the same edit
in reverse, and any projections already written are ordinary Markdown the
learner can keep or delete.
