export const meta = {
  name: 'obsidian-export-impl',
  description: 'Implement Obsidian session-memory export (Tier 1+2) across agent-session-tools and studyloop packages',
  phases: [
    { title: 'Foundation', detail: 'config accessor, writer module, studyloop settings, install wizard, doctor — 5 parallel agents on distinct files' },
    { title: 'CLI', detail: 'wire --obsidian flags into export_sessions.py' },
    { title: 'Tests', detail: 'write tests for both packages — 2 parallel agents' },
    { title: 'Verify', detail: 'ruff + full pytest + fix failures' },
  ],
}

const WT = '/Users/user/code/personal/tools/StudyLoop/.claude/worktrees/obsidian-export'
const SPEC = `${WT}/docs/designs/obsidian-export.md`

const COMMON = `
You are implementing part of an approved feature in a git worktree.
WORKTREE ROOT (cwd): ${WT}
DESIGN SPEC (read it FIRST, it is ground truth): ${SPEC}

Hard rules:
- Python: type hints required, ruff-clean, docstrings on public functions. Match surrounding style.
- Run any commands with: env -u VIRTUAL_ENV uv run <cmd>   (a VIRTUAL_ENV env conflict otherwise reuses the wrong venv).
- IMPORT BOUNDARY: code in packages/agent-session-tools/ must NOT import from studyloop, and vice-versa. They share config.yaml but never import each other.
- Do NOT git commit and do NOT git add. Leave changes in the working tree.
- Do NOT edit packages/studyloop/src/studyloop/web/static/index.html (uncommitted work lives there).
- Do NOT run the full test suite (a later phase does that). You MAY run ruff on the file(s) you changed.
- Stay strictly within your assigned files. Other agents are editing other files concurrently.
Return a concise summary: what you changed (file:line), the public signatures you added, and anything the CLI/test phases must know.
`

phase('Foundation')

const foundation = await parallel([
  // A — config accessor in agent-session-tools
  () => agent(`${COMMON}
TASK A — Config accessor (agent-session-tools).
File: packages/agent-session-tools/src/agent_session_tools/config_loader.py
1. Add an "obsidian" block to DEFAULT_CONFIG (after "semantic_search") matching the spec's config schema:
   enabled/export_enabled flag (default False), vault_path (default ~/Obsidian/Personal), memory_dir "AgentMemory",
   moc_dir "AgentMemory/MOC", backlinks True, granularity "both", filename_template "$date-$source-$slug".
   Use the key name "obsidian". For the gate flag use "export_enabled".
2. Add a get_obsidian_config(config: dict | None = None) -> dict[str, Any] accessor that mirrors get_semantic_config:
   returns config.get("obsidian", DEFAULT_CONFIG["obsidian"]).
3. In load_config(), expand the obsidian vault_path via expand_path (mirror how database.path is expanded near line 194),
   guarding for the key's presence.
Keep it minimal. Run: env -u VIRTUAL_ENV uv run ruff check packages/agent-session-tools/src/agent_session_tools/config_loader.py
Report the EXACT signature and the obsidian dict keys you used so the writer/CLI agents match them.`,
    { label: 'config-accessor', phase: 'Foundation' }),

  // B — writer module (new file)
  () => agent(`${COMMON}
TASK B — The Obsidian writer module (NEW FILE, agent-session-tools).
Create: packages/agent-session-tools/src/agent_session_tools/obsidian_writer.py
This is the core of the feature. Read the spec's "Note format", "MOC index notes", and "Backlinking" sections carefully.

Public functions to implement:
- write_session_to_vault(session: dict, messages: list[dict], vault_path: Path, obsidian_cfg: dict | None = None, topic_index: dict | None = None) -> Path | None
    Writes ONE markdown note for a session into <vault_path>/<memory_dir>/. Returns the path written, or None if skipped (idempotent: unchanged content).
    - filename: <YYYY-MM-DD>-<source>-<slug>.md  (slug from basename(project_path) + last 8 chars of session id; lowercase-kebab; safe chars only)
    - frontmatter EXACTLY per spec (type: agent-memory, id, created, updated, status, source_tool, source_project, session_id, git_branch, tags, date, about). Emit a content_hash field for idempotency.
    - body: use agent_session_tools.formatters.format_summary(session, messages) for the Summary/Key Points; add "## Files Touched" only if derivable from messages metadata (otherwise omit); add "## Related" with [[wikilink]]s from matched topics (see backlinks below).
    - IDEMPOTENT: if the target file exists and its content_hash matches, return None (skip). Otherwise overwrite.
    - create memory_dir if missing.
- build_topic_index(vault_path: Path) -> dict[str, str]
    Scan vault .md files (skip dotfolders like .obsidian/.smart-env/.trash/.git), collect note title (filename stem) and any frontmatter aliases. Return {lowercased_term: NoteTitle}. Keep it dependency-light: parse YAML frontmatter with a minimal split on leading '---' blocks and yaml.safe_load; do NOT add new dependencies. Be robust to files without frontmatter.
- inject_backlinks(body_topics: list[str], topic_index: dict[str, str]) -> list[str]
    Return [[NoteTitle]] wikilinks for topics that match the index (case-insensitive). Used to build the ## Related section.
- write_moc(vault_path: Path, obsidian_cfg: dict, project: str, note_ids: list[str]) -> Path
    Regenerate (not append) <vault_path>/<moc_dir>/<project>.md listing note ids reverse-chronologically as [[id]] links, with simple frontmatter (type: agent-memory-moc).
- write_vault_notes(conn, obsidian_cfg: dict, vault_path: Path, session_ids: list[str] | None = None, dry_run: bool = False) -> dict
    Orchestrator called from export. Reads sessions (and their messages) from the sqlite3 connection (conn.row_factory is sqlite3.Row). If session_ids is None, export all. Builds the topic index once (cached). Writes per-session notes + per-project MOCs. Honors granularity ("both" => notes+moc, "session" => notes only). Returns {written: int, skipped: int, mocs: int}. If dry_run, write nothing and just count.
Guards: if vault_path missing/not a dir, print a clear warning and return zero-counts (do NOT crash the export).
Use config_loader.get_obsidian_config / expand_path where helpful, but accept an explicit obsidian_cfg so it is unit-testable without global config.
Do not import from studyloop.
Run: env -u VIRTUAL_ENV uv run ruff check on the new file. Report all public signatures precisely.`,
    { label: 'writer-module', phase: 'Foundation' }),

  // D — studyloop settings
  () => agent(`${COMMON}
TASK D — studyloop Settings dataclass (studyloop package).
File: packages/studyloop/src/studyloop/settings.py
1. Add an ObsidianConfig dataclass (frozen-style like the other *Config dataclasses such as PomodoroConfig / ContentConfig) with fields:
   export_enabled: bool = False, vault_path: Path = (sensible default), memory_dir: str = "AgentMemory",
   moc_dir: str = "AgentMemory/MOC", backlinks: bool = True, granularity: str = "both".
2. Add an "obsidian: ObsidianConfig = field(default_factory=ObsidianConfig)" field to the Settings dataclass (near line 277-285).
3. In load_settings(), add a parse block (mirror the "pomo"/"ct" blocks around lines 404-429) that reads raw.get("obsidian", {}) and populates settings.obsidian. IMPORTANT: if vault_path is absent in the obsidian section, default it to settings.obsidian_base. Coerce vault_path with the existing _path helper.
4. Do NOT touch or rename the existing flat obsidian_base scalar field or _SCALAR_FIELDS — keep backward compat.
Run: env -u VIRTUAL_ENV uv run ruff check packages/studyloop/src/studyloop/settings.py
Report the ObsidianConfig field list and how vault_path defaults to obsidian_base.`,
    { label: 'studyloop-settings', phase: 'Foundation' }),

  // G — install wizard
  () => agent(`${COMMON}
TASK G — Install wizard step (studyloop package).
File: packages/studyloop/src/studyloop/cli/_setup.py  (Step 4, lines ~107-125)
Extend the existing Obsidian step (do NOT rewrite the whole file):
1. After the vault path is captured and confirmed to exist, check for a ".obsidian/" subdir; if absent, print a yellow warning "may not be a vault root" (do not block).
2. Add a click.confirm("  Export agent session-memory notes to this vault?", default=False). If yes, set
   config["obsidian"] = {"export_enabled": True, "vault_path": str(obsidian_raw), "memory_dir": "AgentMemory", "moc_dir": "AgentMemory/MOC", "backlinks": True, "granularity": "both"}.
   Keep writing config["obsidian_base"] = str(obsidian_raw) as today (backward compat).
3. At the merge step (line ~144), add "obsidian" to the tuple of nested-merge keys so the obsidian sub-dict merges instead of shallow-overwriting.
Match the existing click/console style exactly. Run ruff check on the file. Report the new prompt text and config keys written.`,
    { label: 'install-wizard', phase: 'Foundation' }),

  // H — doctor
  () => agent(`${COMMON}
TASK H — Doctor checks (studyloop package).
Files: packages/studyloop/src/studyloop/doctor/config.py and packages/studyloop/src/studyloop/doctor/_doctor.py
1. Extend check_obsidian_vault() in doctor/config.py: after the existing is_dir() pass branch, before returning "pass", add a ".obsidian/" marker check. If the vault dir exists but has no .obsidian/ subdir, return a "warn" CheckResult ("Vault path exists but .obsidian/ not found" / hint "Ensure this is your Obsidian vault root"). If .obsidian/ exists, keep the existing pass result. Do not break the existing empty/missing branches.
2. Add a new check_obsidian_export() -> list[CheckResult]: load settings; if settings.obsidian.export_enabled is True, verify the resolved vault_path / memory_dir is creatable/writable (a "pass" if the vault dir exists, "warn" if missing). If export not enabled, return an "info" result "Obsidian export disabled". Use the same CheckResult shape as the others.
3. Register check_obsidian_export in _doctor.py (the list at ~line 58 alongside check_obsidian_vault, check_review_directories, check_pandoc, check_tmux_resurrect).
Note: settings.obsidian is added by a concurrent agent; reference settings.obsidian.export_enabled and settings.obsidian.vault_path. Be defensive with getattr(settings, "obsidian", None) in case of load order.
Run ruff check on both files. Report the new check name and registration.`,
    { label: 'doctor-checks', phase: 'Foundation' }),
])

log('Foundation phase complete: ' + foundation.filter(Boolean).length + '/5 agents returned')

phase('CLI')

const cli = await agent(`${COMMON}
TASK C — CLI wiring (agent-session-tools). DEPENDS ON: config_loader.get_obsidian_config and obsidian_writer.write_vault_notes (both now exist in the worktree — read them to confirm exact signatures before wiring).
File: packages/agent-session-tools/src/agent_session_tools/export_sessions.py
1. Add Typer options to main(): --obsidian/--no-obsidian (bool, default None so config gate decides), --obsidian-vault (Path|None), --obsidian-backfill (bool), --obsidian-dry-run (bool).
2. Thread these into _run_export(...) via new params (obsidian: bool|None, obsidian_vault: Path|None, obsidian_backfill: bool, obsidian_dry_run: bool).
3. In _run_export, AFTER conn.commit() (line ~190) and BEFORE conn.close() (line ~210): resolve obsidian config via get_obsidian_config(); decide enabled = explicit --obsidian flag if given else cfg["export_enabled"]; resolve vault_path (flag > cfg["vault_path"] > config obsidian_base). If enabled, call obsidian_writer.write_vault_notes(conn, cfg, vault_path, session_ids=<all if backfill else only the ids added/updated this run>, dry_run=obsidian_dry_run) and print a one-line summary of the returned counts.
   - For the non-backfill case you need the ids touched this run. If _run_export does not already track them, collect newly added/updated session ids (the exporters/commit_batch know status). Simplest robust approach: query sessions whose updated_at changed in this run, OR pass backfill=all when --obsidian-backfill else fall back to all-with-idempotent-skip (the writer is idempotent, so exporting all and letting the writer skip unchanged is acceptable and simplest — prefer this unless you can cheaply get the touched ids).
4. Update the main() docstring examples to mention --obsidian.
Keep DB write path untouched. Run ruff check on the file. Report the final flag set and exactly how session_ids is determined.`,
  { label: 'cli-wiring', phase: 'CLI' })

phase('Tests')

const tests = await parallel([
  () => agent(`${COMMON}
TASK I — Tests for agent-session-tools. Read the implemented obsidian_writer.py, config_loader.py changes, and export_sessions.py changes first.
Create: packages/agent-session-tools/tests/test_obsidian_writer.py
Follow existing conventions (see tests/conftest.py fixtures temp_db/populated_db, tests/test_formatters.py for pure-dict tests, tests/test_export_cli.py for CliRunner).
Cover:
- write_session_to_vault creates a .md file in <vault>/AgentMemory with correct frontmatter keys (type: agent-memory, id, session_id, etc.).
- idempotency: second call with unchanged session returns None / writes no new file.
- build_topic_index picks up note stems + aliases and skips dotfolders.
- inject_backlinks returns [[Title]] for matched topics, nothing for unmatched.
- write_moc creates an MOC file listing [[id]] links.
- write_vault_notes orchestration over populated_db: returns counts, honors dry_run (writes nothing), honors granularity.
- config: get_obsidian_config returns the obsidian dict; with STUDYLOOP_CONFIG pointing at a temp yaml that sets obsidian.vault_path.
- CLI: CliRunner invoke of the export app with --obsidian --obsidian-vault <tmp> --obsidian-dry-run writes nothing; without dry-run writes notes. Guard: --no-obsidian / gate-off writes nothing.
Use tmp_path as vault root. Run ONLY your new test file: env -u VIRTUAL_ENV uv run pytest packages/agent-session-tools/tests/test_obsidian_writer.py -q
Iterate until your file passes. Report pass count and any impl bug you found (note it, do not fix impl in other agents' files unless trivial and clearly correct).`,
    { label: 'tests-ast', phase: 'Tests' }),

  () => agent(`${COMMON}
TASK J — Tests for studyloop (settings, setup wizard, doctor). Read the implemented settings.py ObsidianConfig, _setup.py step, and doctor/config.py changes first.
1. Extend/add settings tests: ObsidianConfig loads from a yaml obsidian: section; vault_path defaults to obsidian_base when absent. Put in the existing settings test module if present (search tests for load_settings) else a new test_settings_obsidian.py.
2. Extend packages/studyloop/tests/test_setup_wizard.py: drive the wizard with CliRunner piping stdin that answers yes to Obsidian + yes to export, assert the written config has obsidian.export_enabled True and obsidian_base set.
3. Extend packages/studyloop/tests/test_doctor_config.py: a vault dir WITH .obsidian/ passes; a vault dir WITHOUT .obsidian/ warns; check_obsidian_export returns info when disabled and pass/warn when enabled.
Run ONLY the studyloop tests you touched, e.g.: env -u VIRTUAL_ENV uv run pytest packages/studyloop/tests/test_setup_wizard.py packages/studyloop/tests/test_doctor_config.py -q  (plus the settings test).
Iterate until they pass. Report pass counts and any impl bug found.`,
    { label: 'tests-sl', phase: 'Tests' }),
])

log('Tests phase complete: ' + tests.filter(Boolean).length + '/2 agents returned')

phase('Verify')

const verify = await agent(`${COMMON}
TASK K — Full verification and cleanup. This is the gate.
1. Format + lint the whole worktree: env -u VIRTUAL_ENV uv run ruff format . && env -u VIRTUAL_ENV uv run ruff check . --fix
2. Run the FULL test suite for both packages: env -u VIRTUAL_ENV uv run pytest packages/agent-session-tools packages/studyloop -q
3. If ANY test fails: read the failure, fix the root cause in the appropriate source file (you may edit any source file in the worktree EXCEPT web/static/index.html), and re-run. Iterate until green or until you hit a genuine blocker.
4. Confirm the import boundary holds (agent-session-tools must not import studyloop): env -u VIRTUAL_ENV uv run python -c "import agent_session_tools.obsidian_writer"  should succeed without importing studyloop.
5. Do a quick smoke test of the writer against a temp vault if feasible (do NOT write to the real ~/Obsidian).
Do NOT git commit.
Report: final ruff status, final pytest pass/fail counts (exact numbers), any tests you had to fix and why, and any remaining known issues or follow-ups. Be honest about failures — do not claim green if it is not.`,
  { label: 'verify', phase: 'Verify' })

return {
  foundation: foundation.map((r, i) => ({ agent: ['config','writer','settings','wizard','doctor'][i], ok: !!r })),
  cli: !!cli,
  tests: tests.map(Boolean),
  verify_summary: verify,
}
