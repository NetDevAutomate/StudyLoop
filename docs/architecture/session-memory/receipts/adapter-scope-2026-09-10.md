# Adapter scope receipt — six supported adapters (2026-09-10)

**Ruling (Andy, 2026-09-10):** the supported adapters are exactly **kiro-cli, Claude Code,
Codex, OpenCode, pi, Grok Build** ("grok builder"). Nothing else, at any layer. This
supersedes the 2026-08 ruling that dropped grok from the release contract (`80d24e48`).

**Scope of this receipt:** Stage 1 of the reconciliation plan — inventory and classify every
reference to an out-of-scope name, and establish Grok CLI's real conventions from its own
documentation before any adapter is written. No product code was changed in this stage.

Recorded on `main` @ `ec5fb93d`. Inventory produced by three read-only sub-agent lanes
(`778ae007` studyloop package + docs, `1238f84e` agent-session-tools + git history,
`205c70fa` Grok CLI primary sources); every load-bearing claim below was re-verified by the
orchestrator against the cited file or command before being written here.

---

## 1. State of each layer, as found

| Layer | File | State on `main` | Gap vs. the six |
|---|---|---|---|
| Session exporters | `packages/agent-session-tools/src/agent_session_tools/exporters/__init__.py` | `EXPORTERS = {claude, codex, grok, kiro, opencode, pi}` | **none** |
| Export CLI sources | `.../agent_session_tools/export_sessions.py:163` | `SOURCE_CHOICES` = same six; `--grok-only` present | none |
| Native parser versions | `.../agent_session_tools/context/capture.py:209` | `codex, claude_code, kiro_cli, grok` | none (opencode/pi use the pi-family path) |
| Harness contract | `packages/studyloop/src/studyloop/harnesses.py` | `CORE=(kiro,codex,claude)`, `PREVIEW=(opencode,pi)` | **grok missing** |
| Launch adapters | `packages/studyloop/src/studyloop/adapters/` | claude, codex, kiro, opencode, pi | **`grok.py` deleted in `80d24e48`** |
| Installer targets | `packages/studyloop/src/studyloop/installers.py` | `_AGENT_CHOICES = RELEASE_HARNESSES`; `_TOOL_LINKS` has no grok | **grok LinkSpec + binary probe missing** |
| Doctor | `packages/studyloop/src/studyloop/doctor/agents.py:26-35` | `TOOL_AGENTS` five entries; **module-level `assert tuple(TOOL_AGENTS) == RELEASE_HARNESSES`** | must be edited in the same change as `harnesses.py` or the package fails at import |
| ACP-capable set | `.../web/services/session_start.py:17` | `frozenset({"kiro"})` | grok had a real ACP path before `80d24e48` |
| ACP argv | `.../web/routes/session/_transport.py:141-143` | only `kiro-cli acp`; else `ValueError` | grok argv removed |
| Extractor scope predicate | `packages/studyloop/src/studyloop/extractors/pipeline.py:32` | `STUDY_SOURCES = frozenset(SESSION_SOURCE_BY_HARNESS.values())` | follows `harnesses.py` automatically |
| Docs harness lists | 26 locations (see §2.5) | five harnesses | grok to add; `docs/agent-install.md:15` explicitly denies grok |
| Live `~/.config/studyloop/sessions.db` | 5,879 sessions, 14 source labels | 1,279 rows under 7 retired labels; 6 rows `study_mentor` (first-party, see §4) | data, not adapters |

Live source-label census (read-only, `SELECT source, count(*)`):
`claude_code 3603 · kiro_cli 614 · repoprompt 440 · aider 422 · codex 307 · kilocode_cli 131 ·
litellm-proxy 124 · gemini_cli 87 · bedrock_proxy 71 · grok 53 · opencode 14 · study_mentor 6 ·
omp 4 · pi 3`.

**There is no aider, kilocode, repoprompt, litellm-proxy, bedrock_proxy, omp or gemini adapter
module anywhere in the tree** (`git ls-files packages/*/src` confirms; the only matches are
stale `__pycache__`/`.ruff_cache` bytecode from before `80d24e48`). The earlier census
finding "fix the aider/kilocode adapter" was mis-stated: those rows are legacy data.

---

## 2. Residue classification

Names searched (word-boundary, case-insensitive): aider, kilocode(_cli), repoprompt,
litellm-proxy/litellm_proxy, bedrock_proxy/bedrock-proxy, gemini(_cli), omp, amp,
antigravity, study_mentor. Excluded: `web/static/vendor/**`, `.git`, `.venv`, `.worktrees`,
`node_modules`. Totals: **173 hits in 54 files** (Lane A 164/45 + Lane B 9/9).

| Category | Hits | Meaning | Action |
|---|---|---|---|
| adapter-residue | 74 | treats the name as a harness, exporter, installer target or session source | remove / rename / edit in Stage 3 (Stage 2 for the grok-related ones) |
| content-provider | 45 | the **Google Gemini API** as a card-generation LLM provider (`GEMINI_API_KEY`, `provider_profiles.py`) | **keep** — a provider axis, not an adapter |
| negative-test | 23 | asserts the name is *not* supported | keep as guards, except the two that lock grok out (must flip) |
| historical | 16 | CHANGELOG, `releases/archive`, rationale prose, dated comments | keep, immutable |
| false-positive | 15 | `&amp;` HTML entities, `.aider/` generic tool-cache ignore, Andy's local LiteLLM gateway path in an opt-in live test | keep |
| legacy-data-label | **0** | code handling a retired label for historical rows | nothing to decide — `pre_filter` rejects unsupported sources generically |

### 2.1 adapter-residue — the actionable rows

| path:line | snippet | action |
|---|---|---|
| `.gitignore:461` | `GEMINI.md` | remove |
| `.gitignore:463` | `!/GEMINI.md` | remove (file no longer exists, CHANGELOG:424) |
| `.gitignore:464-465` | comment `pi/omp harness steering files … --tool pi\|omp` | edit to pi only |
| `.gitignore:468` | `!agents/omp/AGENTS.md` | remove — `agents/omp/` does not exist |
| `.gitignore:471` | `!agents/gemini/GEMINI.md` | remove — `agents/gemini/` does not exist |
| `.gitignore:508-510` | negation for `pi-omp-harness-integration.md` | retarget to the renamed pi-only doc |
| `docs/architecture/pi-omp-harness-integration.md` (43 hits) | omp treated throughout as an installable/exportable harness; stale 9-value `_AGENT_CHOICES` literal (l.152); broken link to `docs/troubleshooting/pi-omp.md` (l.287, missing); **nothing links to this file** | rewrite to pi-only as `docs/architecture/pi-harness-integration.md` (it is the only written description of the pi JSONL exporter and mtime detection); drop the omp halves and the dead link |
| `docs/session-protocol.md:6` | "All agents (Kiro, Claude Code, Gemini, OpenCode)…" | rewrite to the six |
| `docs/session-protocol.md:9` | "ACP … Kiro + Gemini today" | Kiro + Grok Build |
| `docs/architecture/c4-test-suite-context.md:12` | `"Kiro, Gemini, or provider…"` | edit |
| `docs/architecture/test-suite-design.md:125` | "real Kiro/Gemini/provider behaviour" | edit |
| `scripts/plan_agent_harness.py:97-99` | `"gemini": Harness(name="gemini", binary="gemini", …)` | remove entry |
| `packages/agent-session-tools/src/agent_session_tools/mcp_server.py:280` | tool docstring "(claude, kiro, gemini, opencode, etc.)" | list the six — this text is what an LLM reads as the tool description |
| `packages/agent-session-tools/tests/test_export_cli_pi_omp.py` (filename) | omp not a source anywhere in the body | rename `test_export_cli_sources.py` |
| `packages/studyloop/tests/test_install_agent_contracts.py:83` | `ignored_names = {"GEMINI.md"}` | remove dead exclusion |
| `packages/studyloop/tests/test_adapter_custom.py:14-46` (11) | custom-adapter fixture `binary: "aider"` | rename fixture value to an obviously fictional binary |
| `packages/studyloop/tests/test_settings_custom.py:552-564` (4) | `agents.custom` fixture `"aider"` | same |
| `packages/studyloop/tests/test_acp_normaliser.py:39` | `rewrite_outbound_method(…, "gemini")` | use a supported agent name |
| `packages/studyloop/tests/test_agent_launcher.py:127` | `STUDYLOOP_AGENT=gemini` as the not-installed exemplar | use a fictional name |
| `packages/studyloop/tests/test_session_cleanup.py:264-265` | mock adapter keyed `"gemini"` | use a fictional name |
| `packages/studyloop/tests/test_web_session_lifecycle.py:471-493` | stubbed error "Install the Gemini CLI" exemplar | use a fictional name; keep l.359 guard `"Gemini" not in hint_text` |
| `packages/studyloop/tests/test_web_acp_agent_matrix.py:5,8,106,389`, `test_acp_transport.py:5` | docstrings "Kiro + Gemini + Grok" | refresh prose (code is derived) |
| `packages/studyloop/tests/{test_web_acp_agent_matrix.py:64, test_web_acp_chat_ui.py:60, test_harness_matrix.py:41}` | "previous literal was [kiro, gemini, grok]: … dropped" | becomes false once grok returns — refresh in Stage 2 |
| `packages/studyloop/src/studyloop/session/transports/__init__.py` | docstring lists "claude, codex, gemini, grok, kiro, opencode" | rewrite to the six |

### 2.2 negative-tests that MUST flip in Stage 2 (they lock grok out)

| path:line | assertion | change |
|---|---|---|
| `packages/studyloop/tests/test_release_harnesses.py:18` | `assert "grok" not in RELEASE_HARNESSES` | flip to `in`; keep l.17 (`gemini not in`) |
| `packages/studyloop/tests/test_extractor_product_boundary.py:20` | `find_spec("studyloop.adapters.grok") is None` (tuple `gemini, grok, ollama, lmstudio`) | drop `grok` from the tuple |
| `packages/studyloop/tests/test_settings_custom.py:533-537` | `priority: [pi, gemini, grok, claude]` → expects `[pi, claude]` | expect `[pi, grok, claude]` |
| `docs/agent-install.md:15` | "Gemini CLI, Antigravity, and Grok are not mentor harnesses" | drop Grok |
| `packages/studyloop/tests/test_docs_no_gemini_mentor_claims.py:4` | guard text "plus OpenCode and pi (preview)" | add Grok Build |

Guards that stay: `test_docs_no_gemini_mentor_claims.py` (whole file; lines 53-60 assert the
Gemini *provider* must survive), `test_release_harnesses.py:17`,
`test_extractor_pipeline.py:120` (`pre_filter("s1","aider",…) is False`),
`test_web_session_lifecycle.py:359`, `test_export_cli_pi_omp.py:79-80,133`.

### 2.3 content-provider (keep, 45 hits / 17 files)

All are the **Google Gemini API** used for card generation, never the Gemini CLI:
`web/routes/content_gen/_secrets.py:24`, `secrets.py:37,77,90,360,455`,
`content/generators/provider_profiles.py:8,83,124-158`, `content/generators/__init__.py:141`,
`content/generators/openai_compat.py:4`, `settings.py:250`, `.env.example:15`,
`docs/content-pipeline.md:66-105` (l.69-70 is the disambiguation prose the R-65 guard depends
on), `docs/troubleshooting.md:162`, `docs/architecture/{current.md:3,37,65; target.md:114}`,
`docs/system-overview.md:46,179`, `docs/contributing.md:278`, tests `test_web_secrets_route.py`,
`test_web_content_providers.py:60`, `test_provider_profiles.py:20,56`, `test_secrets.py` (8).

### 2.4 historical / false-positive (keep)

Historical: `CHANGELOG.md:312,424-425`; `releases/archive/v2.6.0-unreleased.md:16-17`;
`migrations.py:933` (why v25 rebuilt FK cascades); `test_acp_transport.py:516` and
`test_acp_normaliser.py:32` (Gemini CLI source cited as *provenance* for the ACP permission
wire protocol — a citation, not a support claim); `test_no_dangling_symlinks.py:3-5`;
`tests/fixtures/lane_ownership.yaml:103`.
False positives: `&amp;` entities (`index.html:1691,2943`, `plans-panel.js:251`,
`formatters.py:106`, `test_formatters.py:173`, `current.md:635`, generated Archify HTML);
`.gitignore:479 .aider/` (generic tool cache); `tests/live/test_wind_down_transcripts.py:67`
(Andy's local `litellm-proxy-docker` gateway for an opt-in live gate — not a harness).

### 2.5 Doc locations that list the supported harnesses (grok to be added in Stage 2)

`README.md:58` · `docs/agent-install.md:13,15,54` · `docs/architecture.md:35` ·
`docs/contributing.md:8` ("Five mentor harnesses" → six) `,272` · `docs/first-week.md:8-9` ·
`docs/obsidian-export.md:5-6` · `docs/setup-guide.md:326,609,845` (l.670 already has grok) ·
`docs/cli-reference.md:522,609` · `docs/session-memory.md:25` (already has grok) ·
`docs/session-protocol.md:6` · `docs/tui-guide.md:18` (ASCII box, width-sensitive) ·
`docs/voice-output.md:66,219` · `docs/second-brain.md:338` · `docs/system-overview.md:32` ·
`docs/architecture/current.md:14,98` · `docs/architecture/target.md:34` ·
`docs/architecture/session-memory/GLOSSARY.md:51` (already has grok) ·
`agents/shared/session-protocol.md:115` · `agents/mcp/README.md:23`.
Docs currently describing grok as **import-only** (must be revised): `docs/agent-install.md:15-18`,
`docs/cli-reference.md:571`, `docs/session-memory.md:41-44`, `docs/setup-guide.md:661`,
`agents/skills/studyloop-session-memory/SKILL.md:80-81`, `MVP-RELEASE.md:45`.

---

## 3. Grok CLI 1.0.13 — conventions from primary sources

Citations are `~/.grok/docs/user-guide/NN-name.md:LINE` or `(command)`. Statements the docs do
not make are marked **undocumented**.

**Identity.** Binary `grok`; `grok --version` → `grok 1.0.13 (5e9a58528b76) [stable]`.
The README calls it "Grok — a terminal-based AI coding assistant and agentic harness"
(`~/.grok/README.md:1-3`); the user guide and the TUI header call it **"Grok Build"**
(`01-getting-started.md:3`; `grok --help` header `Grok Build TUI`). "Grok Builder" is not a
name it uses. `~/.grok/bin/agent` is a second symlink to the same binary.

**Instruction files.** Per directory, in order: `Agents.md, Claude.md, CLAUDE.md,
CLAUDE.local.md, AGENT.md, AGENTS.md` (`12-project-rules.md:15-24`). Repo rules are read from
the git root down to CWD; outside a git repo, **CWD only** (`:55-56`). Deeper files win
(`:73-77`). Rules directories always scanned: `<dir>/.grok/rules/` (`:34`) and
`$GROK_HOME/rules/` (`:42`, applies to *all* projects — unsuitable for a study persona).
**There is no `GROK.md`** (`:190`). Named agent definitions exist as Markdown + YAML
frontmatter in `~/.grok/agents/` or `.grok/agents/` (`05-configuration.md:818,824`;
`26-config-reference.md:40-41`), selected with `--agent <NAME>` / `GROK_AGENT`; their full
schema is **undocumented** (only `name, description, tools, mcpInheritance, mcpServers, hooks,
permissionMode` appear). `grok inspect [--json]` shows what loaded (`12-project-rules.md:211`).

**Launch flags** (`grok --help`, cross-cited `14-headless-mode.md:21-45`): positional
`[PROMPT]` seeds an interactive session; `-p/--single` single-turn to stdout;
`-m/--model`; `--cwd`; `-r/--resume [ID|title]` (`17-sessions.md:203-209`); `-c/--continue`
(most recent for CWD); `-s/--session-id` (new session, given UUID); `--rules "<text>"`
appended in a `<human_rules>` block (`12-project-rules.md:171`); `--system-prompt-override`;
`--always-approve` (= `--yolo` = `--permission-mode bypassPermissions`); `--no-alt-screen`
inline TUI; `--output-format plain|json|streaming-json|streaming-messages-json`.
`--trust` is named at `10-hooks.md:78` but **absent from `grok --help` in 1.0.13**.

**ACP.** Fully documented: "Agent mode runs Grok as a long-lived server that clients talk to
over ACP (JSON-RPC)" (`15-agent-mode.md:1-3`). stdio launch: **`grok agent --always-approve
stdio`** (`15-agent-mode.md:45-50`; `grok agent --help` lists `stdio, headless, serve,
leader`). Lifecycle `initialize → session/new(cwd, mcpServers) → session/prompt →
session/update` (`:96-104`); `session/load` resumes (`17-sessions.md:226-247`); `_meta`
options `rules, systemPromptOverride, agentProfile, yoloMode, autoMode` (`:176-190`). Zed,
Neovim, Emacs listed as clients (`:212-220`). Pre-`80d24e48` StudyLoop used argv
`["grok","agent","stdio"]` without `--always-approve`; whether StudyLoop's ACP client answers
`session/request_permission` itself is what decides the flag (see §5 Stage 2).

**Sessions.** Root `~/.grok/sessions/`, overridable by **`GROK_HOME`** (`17-sessions.md:18`).
Group dir = URL-encoded CWD (`:24`); layout `<encoded-cwd>/<uuidv7>/{summary.json,
updates.jsonl, chat_history.jsonl, plan.json, rewind_points.jsonl, signals.json, feedback.jsonl,
compaction_checkpoints/, subagents/}` (`:27-37`). `updates.jsonl` is "the authoritative
conversation log" (`:39`). `summary.json` fields are documented (`:339-350`);
**`chat_history.jsonl`'s record format is undocumented** (`:30`, `:354` are prose only).
`GrokExporter` parses `chat_history.jsonl` + `summary.json` — it has ingested 53 sessions, but
it is built on an undocumented format (follow-on, §6). Layout matches disk exactly.

**Hooks.** Lifecycle events include `SessionStart` and **`SessionEnd`** (carries
`subagentType` for child sessions) (`10-hooks.md:88-104`). Global hooks in
`~/.grok/hooks/*.json` need no folder trust (`:65,78`); project hooks do. JSON shape
`{"hooks":{"SessionEnd":[{"hooks":[{"type":"command","command":"…","timeout":10}]}]}}`
(`:137-156`). Env: `GROK_HOOK_EVENT, GROK_SESSION_ID, GROK_WORKSPACE_ROOT` (`:450-456`).
SessionEnd shares a ~10 s exit budget — "keep it to a local write" (`:387-388`).

**MCP.** `~/.grok/config.toml` `[mcp_servers.<name>]` with `command, args, env, enabled`
(`07-mcp-servers.md:19,27-36`); project scope `.grok/config.toml` replaces a same-named global
entry wholesale (`:151-178`). CLI: `grok mcp add <NAME> [-s user|project] -- <cmd> [args]`
(`grok mcp add --help`, "Add or update" → idempotent). Tools appear as `server__tool`
(`:186-189`). Live machine: `session-db` is already registered; `studyloop-mcp` is not.

**Skills.** `SKILL.md` directories under `./.grok/skills/`, `<repo>/.grok/skills/`,
`~/.grok/skills/` plus `~/.claude/skills/` compat (`08-skills.md:19-27`); the live
`~/.grok/skills/` is ~82 symlinks into `~/.kiro/skills` and `~/.claude/skills`.

**Permissions/sandbox.** Sandbox off by default (`18-sandbox.md:5`); permission default is
*ask* (`22-permissions-and-safety.md:35`), remedy for unattended runs is `--always-approve`
(`:21,71`). Nothing blocks a PTY launch with a seeded prompt; folder trust gates only
*project* hooks/MCP/LSP (`10-hooks.md:78-80`).

---

## 4. Decisions taken in Stage 1 (in-scope judgement calls, all reversible)

1. **Label and tier.** Harness `grok` → label **"Grok Build"** (the product's own name), binary
   `grok`, **preview** tier alongside opencode and pi (`RELEASE_HARNESSES` order becomes
   `kiro, codex, claude, opencode, pi, grok`; `SESSION_SOURCE_BY_HARNESS["grok"] = "grok"`).
2. **Instruction delivery = the codex pattern**, exactly as the deleted adapter did: write
   `AGENTS.md` into the session directory (Grok reads CWD-only outside a git repo,
   `12-project-rules.md:56`) and launch the bare binary; resume with `grok --resume`. The
   install-time `LinkSpec("agents/codex/AGENTS.md", "{repo_root}/AGENTS.md")` is restored
   **shared with codex** — both harnesses read the same repo-root file, so one source file is
   correct and a copy would drift. No `agents/grok/` directory (none ever existed). Docs must
   say so. Named-agent (`~/.grok/agents/*.md`) and `~/.grok/rules/` routes are rejected:
   undocumented schema, and rules apply to every project.
3. **ACP is restored** for grok (`ACP_CAPABLE_AGENTS` gains `grok`; `_transport._build_argv`
   returns `["grok", "agent", "stdio"]`), because it is documented and the derived ACP matrix
   tests run against a fake transport. Stage 2 adds `--always-approve` **only if**
   `test_acp_transport.py` shows StudyLoop does *not* answer `session/request_permission`.
4. **`study_mentor` stays.** It is not a retired label: `tutor-checkpoint`
   (`agent_session_tools.tutor_checkpoint:main`, `pyproject.toml:51`) writes it live as a
   first-party checkpoint source (`tutor_checkpoint.py:42`). It is a **first-party internal
   source, not a harness**: excluded from the harness parity guard, included in the Stage 4
   read-scope allow-list. Hidden legacy rows are therefore **1,279 across 7 labels**
   (repoprompt 440, aider 422, kilocode_cli 131, litellm-proxy 124, gemini_cli 87,
   bedrock_proxy 71, omp 4), not 1,285 across 8.
5. **Scope predicate: reuse, don't duplicate.** `STUDY_SOURCES` in `extractors/pipeline.py`
   is already derived from `SESSION_SOURCE_BY_HARNESS`; Stage 4 promotes it to a shared
   constant and mirrors it in agent-session-tools from the exporters' `source_name` values
   (plus `study_mentor`), with the Stage 3 parity guard asserting the two agree.
6. **Fixture names.** `aider` as a made-up custom-adapter binary is renamed to an obviously
   fictional name so the Stage 6 zero-reference grep is unambiguous. `gemini` exemplars in
   four tests are swapped likewise; the negative guards are kept.
7. **`pi-omp-harness-integration.md`** is rewritten to pi-only rather than deleted — it holds
   the only written description of the pi JSONL exporter. Its dead `troubleshooting/pi-omp.md`
   link goes.
8. **`.gitignore` receipts negation.** `docs/architecture/session-memory/*` is ignored on
   `main` (`.gitignore:524`), so this receipt could not have been committed — the same silent
   drop the feature branch hit. `!docs/architecture/session-memory/receipts/` is added on
   `main`, byte-identical to `feat/knowledge-proof:.gitignore:527`, so the branches merge clean.

---

## 5. Work orders derived for the next stages

### Stage 2 — restore grok as a launchable harness (`main`)

| File | Change |
|---|---|
| `packages/studyloop/src/studyloop/adapters/grok.py` | restore verbatim from `git show 80d24e48^:…/adapters/grok.py` (satisfies today's `_protocol.py:18-53` with zero gaps; structurally identical to `codex.py`); add `encoding="utf-8"` to match `pi.py:17` |
| `harnesses.py` | `PREVIEW_HARNESSES += ("grok",)`; `HARNESSES["grok"] = Harness("grok", "Grok Build", "grok", False)`; `SESSION_SOURCE_BY_HARNESS["grok"] = "grok"` |
| `doctor/agents.py:26-32` | `TOOL_AGENTS["grok"] = ("grok", "{repo_root}/AGENTS.md")` **in `RELEASE_HARNESSES` order** — the module-level asserts at l.34-35 fire at import otherwise |
| `installers.py` | `_TOOL_LINKS["grok"] = (LinkSpec("agents/codex/AGENTS.md", "{repo_root}/AGENTS.md"),)`; re-add `shutil.which("grok")` to the availability probe; `_AGENT_CHOICES` follows `RELEASE_HARNESSES` |
| `agent_launcher.py` | re-add `from studyloop.adapters.grok import _grok_launch, _grok_setup` and the two `__all__` entries (compat re-export locked by `test_agent_launcher.py`) |
| `settings.py` | update the commented `agents.priority` example; live default derives from `RELEASE_HARNESSES` |
| `web/services/session_start.py:17` | `ACP_CAPABLE_AGENTS = frozenset({"kiro", "grok"})` |
| `web/routes/session/_transport.py:141-143` | `if _config.agent == "grok": return ["grok", "agent", "stdio"]` (+ `--always-approve` per §4.3) |
| `web/routes/session/_models.py` | re-add install hint `"grok": "Install Grok Build: curl -fsSL https://x.ai/cli/install.sh \| bash"` (`01-getting-started.md:13`); ACP transport description "Kiro and Grok Build" |
| `web/routes/session/_options.py` | derives from `HARNESSES` — verify only |
| `web/static/index.html` (~l.2302) | picker hints: PTY "Works with Claude Code, Codex, Grok Build, Kiro, OpenCode, and pi"; ACP "Works with Kiro and Grok Build" |
| `session/transports/__init__.py` | docstring |
| tests | restore `TestGrokAdapter` in `test_adapter_builtins.py` and `test_agent_launcher.py`, `test_detect_grok` + `test_grok_definition_uses_repo_agents_md` in `test_doctor_agents.py`; flip the five items in §2.2; add grok to the surviving loops in `test_settings_custom.py` / `test_study_integration.py`; refresh the three "previous literal" comments |
| docs | add Grok Build to every location in §2.5; revise the six "import-only" statements; `docs/agent-install.md` gains a Grok Build section noting the shared repo-root `AGENTS.md` with Codex |
| verify | `uv run pytest packages/studyloop -q`; `studyloop doctor` lists grok; `get_harness("grok")` resolves |

### Stage 3 — residue removal + parity guard (`main`)

Apply every row of §2.1 not already handled by Stage 2. Add `packages/studyloop/tests/test_adapter_parity.py` asserting, from one literal `EXPECTED = ("kiro","codex","claude","opencode","pi","grok")`: `RELEASE_HARNESSES` set-equal; `set(HARNESSES) == set(TOOL_AGENTS) == set(installers._TOOL_LINKS)`; `agent_session_tools.exporters.EXPORTERS` keys and `SOURCE_CHOICES` equal `{claude, codex, grok, kiro, opencode, pi}`; `STUDY_SOURCES == {kiro_cli, codex, claude_code, opencode, pi, grok}`; `README.md:58`'s harness sentence names all six labels. Finish: the Stage 6 grep for the ten out-of-scope names returns zero hits outside `web/static/vendor/**`, `CHANGELOG.md`, `releases/archive/**`, and the guard tests.

### Stage 4 — scope the live data without deleting it (`main` + worktree)

Promote `STUDY_SOURCES` to `studyloop.harnesses.SUPPORTED_SOURCES`; add
`agent_session_tools.exporters.SUPPORTED_SOURCES = frozenset(e.source_name …) | {"study_mentor"}`
(note `EXPORTERS["pi"]` is a class — instantiate or read its family labels). Apply at:
`mcp_server.py` `session_search`/`session_list` default filter, the `search-cmd` CLI, the
archive adapter on `feat/knowledge-proof`, and `paraphrase_census.py`. Doctor line:
"1,279 sessions in 7 retired sources (hidden, not deleted)". **No row is deleted** — the DB is
the only surviving copy of ~89 % of history; hard deletion requires Andy's explicit
per-run instruction and a `.bak` first.

---

## 6. Follow-ons outside this plan (recorded, not scheduled)

- **Grok session-end capture.** `SessionEnd` global hook (`~/.grok/hooks/studyloop.json`,
  no trust needed) running `session-export --grok-only` as a local write within the 10 s
  budget; would be the one legitimate reason to create `agents/grok/`. pi has the equivalent
  `studyloop-session-export.ts` extension; grok has no `_HARNESS_EXPORT` mandate today.
- **`GrokExporter` reads an undocumented file.** `chat_history.jsonl` has no documented record
  format; `updates.jsonl` is the documented authoritative log (`17-sessions.md:39`). Verify
  the exporter against a real 1.0.13 session (`--grok-only` on the 7 local sessions) and
  consider migrating to `updates.jsonl`.
- **`scripts/plan_agent_harness.py`** registry (kiro/claude/codex) — add grok if the shape is
  identical; otherwise leave (maintainer script).
- **`grok mcp add studyloop -- …`** registration for the `studyloop-mcp` server so
  `get_concept_context` etc. reach Grok Build sessions (parity with the 2026-09-09 wiring for
  the other harnesses).
