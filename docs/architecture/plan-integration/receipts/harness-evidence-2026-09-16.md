# Harness release evidence — pi, OpenCode, Grok Build (issue #21) — 2026-09-16

Unattended overnight run on the owner's macOS machine (`macOS-27.0-arm64`),
worktree `feat/harness-tier-promotion` off `main @ f8cca681`. Every number
below is command output captured by `scripts/harness-evidence.py` into the
per-harness JSON/Markdown receipts in `harness-evidence-2026-09-16/`
(redacted at capture time: the VALUE of every credential-shaped environment
variable is replaced by `<redacted:NAME>` before a byte is written). Secret
scan of the whole receipt directory before commit: `AWS_BEARER_TOKEN` 0 hits,
`ghp_` 0 hits, and a value-level scan of all six secret names known to the run
(Bedrock token, GitHub token, LiteLLM keys, Grafana password): 0 hits.

Credential handling, as instructed: the Bedrock token and the LiteLLM key were
exported to processes only via `set -a; source <file>; set +a` in the same
shell invocation; never printed, never passed as argv, never written to a file.

## Method

Two modes per harness, always one harness at a time (one-session authority):

| Mode | What the harness sees | What StudyLoop sees | Used for |
| --- | --- | --- | --- |
| **scrubbed scratch** (the lane's default) | empty `HOME`, no credentials, `GROK_HOME` pinned to scratch | scratch config/state/DB/tmux | item 1 (install + doctor), launch mechanics |
| **real-harness-auth** (`STUDYLOOP_ACC_REAL_AUTH=1`, new tonight, opt-in) | its own real home and exported provider credentials — exactly the CLI/tmux production environment | scratch config/state/DB/tmux (`STUDYLOOP_CONFIG/SESSION_DIR/STATE_DIR/DB`) | items 2–5 with a real model |

Binaries: `pi` 0.65.0 (`/opt/homebrew/bin/pi`), `opencode` 1.18.30
(`/opt/homebrew/bin/opencode`), `grok` 1.0.30 (`~/.local/bin/grok`), tmux 3.7b.
`PATH` was prepended with the real tmux and Homebrew bin dirs because mise
shims fail under a scratch `HOME` (`mise ERROR ... not trusted`) — the lane's
presence probe would otherwise pass and the launch fail spuriously.

Verdict rule applied: an item is green only when its own decisive line is a
pass **and**, for item 4, the pane/transcript shows the harness's model was
engaged (not an auth/config error) — the lane's mechanical validators alone
cannot tell those apart (council D-17), which is why turns.json is harvested.

## pi — five of five green → promoted to core

| # | Item | Verdict | Decisive line (receipt) |
| --- | --- | --- | --- |
| 1 | install path + doctor (scratch) | **PASS** | `install exit 0; shared: 3, pi: 3` → `~/.pi/agent/{AGENTS.md, extensions/studyloop-session-export.ts, session-db.md}`; doctor: `agent_pi PASS`, `smoke_pi PASS (pi responds)`, `session_memory_skill_pi PASS`, `export_mandate_pi PASS`, `session_export_hook_pi PASS` (`pi.json`) |
| 2 | session launch (lane, real-auth) | **PASS** | `1 passed`; session-state.json → `study-*` tmux session → pi in main pane → 3 turns → `--end` → `--resume` → `--end`, `mode=ended` both times (`pi-real-auth.json`, bundle `auth_mode=real-auth`) |
| 3 | session export | **PASS** | `session-export --pi-only -o <scratch db>`: `1 sessions row for THIS session with source='pi'` (4 messages, user + assistant), transcript at `~/.pi/agent/sessions/…study-export-evidence-pi-a6626228…` |
| 4 | live release check | **PASS** | lane green **and** a real Socratic reply from `us.anthropic.claude-opus-4-6-v1` (Bedrock, $0.139): pi read `session-state.json` + `session-parking.md` per the persona protocol and answered *"I'm not going to just hand you a definition … what do you think happens when you wrap one function inside another…?"* (`pi-real-auth.json` item 3 pane) |
| 5 | plan-architect mode | **PASS** | `studyloop study --mode plan-architect --agent pi` → `persona_file=…/AGENTS.md`, body starts `# Study Plan Architect` (`plan-architect=True`), agent in pane, `final_mode=ended` |

Scrubbed-scratch control run (`pi.json`): the lane also *passes mechanically*
with no credentials — pi prints `Error: No API key found` to all three turns
(0.01 s each) and the lane cannot tell. That is the reason real-auth mode
exists; see "Findings".

## OpenCode — stays preview (two named blockers)

| # | Item | Verdict | Decisive line (receipt) |
| --- | --- | --- | --- |
| 1 | install path + doctor (scratch) | **PASS** | `install exit 0; opencode: 5` → agents `study-mentor.md` + `study-plan-architect.md`, plugin, `session-db.md`, MCP merged into scratch `opencode.json`; doctor: `mcp_opencode PASS (session-db and studyloop MCP servers registered)`, `agent_opencode PASS`, `smoke_opencode PASS (1.18.30)`, hook + mandate PASS (`opencode.json`) |
| 2 | session launch (lane, real-auth) | **PASS** | `1 passed`; TUI up with the `Study-Mentor` agent selected (persona delivered), full start/turns/end/resume/end lifecycle (`opencode-real-auth.json`) |
| 3 | session export | **FAIL (live)** / PASS-FIXTURE | OpenCode 1.18.30 persists sessions in `~/.local/share/opencode/opencode.db` (SQLite; tonight's two sessions are in its `session`/`message`/`part` tables). `OpenCodeExporter` reads only the legacy `storage/session/**/*.json` tree (last written 2026-02) → `rows for this run: []`. Exporter fixture tests pass (34), i.e. the legacy format still works |
| 4 | live release check | **FAIL (no model reply)** | lane passed mechanically, but every assistant row for tonight's sessions has 0 tokens and no parts; `~/.local/share/opencode/log/opencode.log` 00:12:17: `AI_RetryError: Failed after 3 attempts. Last error: Token Plan usage limit` for `minimax-coding-plan/MiniMax-M2.5` — the provider OpenCode currently selects on this machine is out of quota. Environment, not integration — but no reply was observed, so not green |
| 5 | plan-architect mode | **PASS** | persona at `<session>/.opencode/agents/study-mentor.md` with frontmatter + `# Study Plan Architect` body, agent in pane, `final_mode=ended` |

To go green: (a) teach `OpenCodeExporter` to read `opencode.db` (schema:
`session(id, directory, title, time_created, …)`, `message(id, session_id,
data JSON)`, `part(id, message_id, data JSON)`), (b) re-run with a provider
that has quota (`opencode` default model / `/model`), then `just testacc
opencode` with `STUDYLOOP_ACC_REAL_AUTH=1`.

## Grok Build — five of five green on the CLI/tmux path; promotion deferred to council

| # | Item | Verdict | Decisive line (receipt) |
| --- | --- | --- | --- |
| 1 | install path + doctor (scratch) | **PASS** | `install exit 0; grok: 4`; `grok mcp add --scope user` landed in the **scratch** `~/.grok/config.toml` — doctor `mcp_grok PASS … via /tmp/sl-ev-grok-…/home/.grok/config.toml`; `session_export_hook_grok PASS (SessionEnd)`, mandate PASS, `smoke_grok PASS`; real `~/.grok/{config.toml,user-settings.json,hooks/*}` sha256 **unchanged** before/after (`grok.json`) |
| 2 | session launch (lane, real-auth) | **PASS** | `1 passed` after the adapter fix below; `xai.grok-4.6 on Bedrock` in the pane, `Waiting for response… ⇣1.47k`, then `Preparing read_file (2)…` (persona protocol) (`grok-real-auth.json`) |
| 3 | session export | **PASS** | `session-export --grok-only`: `2 sessions rows from THIS run with source='grok'` (4 messages) from `~/.grok/sessions/…study-harness-matrix-live…/chat_history.jsonl` |
| 4 | live release check | **PASS (caveat)** | lane green with the model visibly engaged; the exported messages are user-side only because the lane's PaneDriver ends the session while Grok is still mid-reply — no *completed* Grok reply was captured tonight |
| 5 | plan-architect mode | **PASS** | `persona_file=…/AGENTS.md`, `plan-architect=True`, agent in pane, `final_mode=ended` |

First real-auth attempt (`grok-real-auth` run 1, superseded): both turns
timed out on Grok's **"Do you trust the contents of this directory?"** modal —
a fresh session dir is never trusted. Fixed in `f0edce6a` (adapter pre-trusts
the session dir in `$GROK_HOME/trusted_folders.toml`, mirroring the Claude
pre-trust); the entries it added to the owner's real file were removed after
the run (file restored to its pre-run content).

Why not promoted tonight: issue #21's definition of done says `grok` remains
preview; the owner's overnight brief re-scoped Grok in. With one green run,
one caveat (no completed reply captured) and a second, shared one (below —
Bedrock bearer-token auth is env-only and the **web** PTY/ACP transports scrub
`AWS_BEARER_TOKEN_BEDROCK` by design, so only the CLI/tmux path can work with
this machine's Grok config), the tier flip for Grok is left to the council
review the DoD already requires. Everything needed to flip it is in this
receipt.

## Findings that changed code tonight (all RED → GREEN, all committed)

| Commit | What the evidence showed | Fix |
| --- | --- | --- |
| `b386571e` | Every harness failed identically before its binary launched: `studyloop study` exits 2 "No context scope configured" in every scratch — the seeded config predates the context-memory scope gate | scratch seed carries `memory.default_scope: unclassified` |
| `37862de9` | The lane never saw its own `session-state.json`: the unit-suite conftest's `STUDYLOOP_SESSION_DIR`/`STUDYLOOP_DB`/`SESSION_CONTEXT_SCOPE` leaked into the scratch child | `build_scratch_child_env` drops every inherited `STUDYLOOP_*` pointer and `SESSION_CONTEXT_SCOPE` |
| `00436f67` | No harness can authenticate in an empty HOME, so the lane could prove launch mechanics but never the model path (pi: "No API key found" ×3 while the lane passed) | opt-in `STUDYLOOP_ACC_REAL_AUTH=1` mode; `auth_mode=real-auth` recorded in bundles; `scripts/harness-evidence.py` |
| `fe7534d6` | A pi session wrote the scratch session dir into the owner's real `~/.claude/settings.json` trust list (caught by the real-home write guard; 90 older such entries already present) | `setup_session_dir` pre-trusts for Claude only |
| `bb59a31b` | pytest-timeout (60 s) killed the lane before its own 90 s per-turn budget — the documented `budget-exhausted` outcome was unreachable | lane module `pytest.mark.timeout(600)`, pinned |
| `f0edce6a` | Grok's directory-trust modal blocked every automated Grok session | adapter pre-trusts the session dir in `trusted_folders.toml` |
| `d3581974` | The new pre-trust wrote unit-test tmp paths into the owner's real `trusted_folders.toml` (5 entries; file not on the guard's watch list) | suite-wide `GROK_HOME` isolation; guard watches the file; entries removed |

Observations not acted on: the `pi` mise shim resolves to a node 26.7.0 that
has no pi installed (Homebrew's 0.65.0 is what actually runs; mise node 26.2.0
holds 0.73.1); `studyloop doctor` reports `agent_grok INFO No manifest entry`
(Grok shares Codex's `AGENTS.md`); ~180 stale `sl-acc-*` tmux socket dirs
accumulate under `/tmp` across unit-test runs (swept tonight); the OpenCode
session-export plugin prints its stdout into the TUI; `PaneDriver` counts a
prompt echo/spinner as a reply, so the lane ends sessions mid-answer.

## Tier decision applied

`CORE_HARNESSES = ("kiro", "codex", "claude", "pi")`, `PREVIEW_HARNESSES =
("opencode", "grok")`, release set unchanged; pi's `Harness.core = True`.
Docs updated in the same commit and pinned by
`tests/test_docs_harness_tier_contract.py` (parses each document's own
statement of the split): `docs/agent-install.md`, `CONTRIBUTING.md`,
`docs/contributing.md`, `agents/shared/install-mentor.md`,
`docs/architecture/current.md`, `docs/architecture/pi-harness-integration.md`,
`docs/acceptance-testing.md`, `openspec/specs/agent-adapters/spec.md`,
`openspec/specs/harness-session-memory/spec.md`.
