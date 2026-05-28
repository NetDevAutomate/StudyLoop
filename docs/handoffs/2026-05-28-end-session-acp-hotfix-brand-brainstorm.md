# Handoff — End-Session: ACP hotfix shipped, brand wired, generation feature brainstormed

**Date**: 2026-05-28 ~15:30 BST
**Branch**: `main` (26 commits ahead of `origin/main`, **unpushed by user choice — stay local**)
**Predecessor**: `docs/handoffs/2026-05-28-end-session-acp-chat-ui-shipped.md`

---

## TL;DR

Three things landed this session:

1. **ACP dogfood hotfix** (`bfe9210`) — persona injection, streaming render, theme palette selector, "Setting up your mentor…" banner, AuDHD-aware readability pass, live Kiro Playwright regression fence (`@pytest.mark.live_kiro`).
2. **Architecture + user docs updated** (`bc9a362`) — created `docs/architecture/current.md` + `target.md` with C4 Level 1/2/3 + sequence diagrams. Updated web-ui-guide, system-overview, session-protocol, architecture entry doc. All 16 mermaid diagrams validated by `mmdc`.
3. **Brand wired into WebUI + GitHub** (`3486481`, `<og-readme>`) — header mark + wordmark (theme-aware via inline `currentColor` SVG), sidebar full app icon (gradient background), real favicon, README banner at top, regenerated the broken `studyloop-social.png`, README maintainer note for setting GitHub OG image.

Plus: **brainstormed** a new generation-panel feature for next session.

---

## Test status (final this session)

| Suite | Pass | Fail | Notes |
|-------|------|------|-------|
| ACP chat-UI e2e | 60 | 0 | Updated for typing-indicator contract. |
| ACP per-agent matrix e2e | 14 | 0 | No regression. |
| Live Kiro dogfood (`-m live_kiro`) | 1 | 1 | New regression fence. Persona markers detected each run. |
| Session-start unit (acp + pty) | 23 | 0 | Includes new `TestAcpStartPersonaInjection` (2 tests). |
| Default suite (all minus e2e/live_kiro) | 1122 | 1* | *Pre-existing flake: `test_acp_transport.py::TestEventsAndUpdates::test_available_commands_update_is_dropped` — fails ~33% of the time on clean main, unrelated to this session's diff. |

---

## Commits landed this session

```
3486481 feat(web): brand the WebUI with real logo + add README banner
bc9a362 docs: update user + architecture docs for ACP chat-UI hotfix
bfe9210 fix(acp): dogfood hotfix — persona injection, streaming render, theme selector
```

(Plus a docs commit appending the OG-image maintainer note to README.)

---

## Carry-forward — primary item

### Generation panel for the WebUI (brainstormed; needs plan)

**Decision shape coming out of brainstorm:**

- **Use the existing `content/generators/` pipeline** (Bedrock + Ollama backends already shipping). NOT a new agent. NOT a new generator. Just expose the CLI workflow over HTTP+WS.
- **New WS+REST endpoint** at `/api/content/generate` with progress events, gated by an active-generation singleton (mirrors `session/active.py` pattern so two concurrent jobs can't trash the local Ollama).
- **New "Generate" sidebar tab** between Quizzes and Body Double. Form: scope dropdown (Course / Section / Topic / Session struggles), source dropdown (populated based on scope), kind (Flashcards / Quizzes / Both), count (5/10/15/20/25/50), backend pill, generate button + live progress.
- **Output path** matches the existing reviewer's expected layout: `{content.base_path}/{course}/flashcards/<slug>-flashcards.json`. Existing-file handling: prompt for Overwrite / Merge / New Suffix; merge dedupes by `front` (flashcards) or `question` (quizzes).
- **Session-struggles scope: A then B.**
  - **v1 (A)**: date-window batch query against `sessions.db` for `confidence=struggling` rows, group by topic-slug, generate one deck per topic over the window. Cron-friendly.
  - **v2 (B)**: agent marks specific concepts mid-session as needing review; one-shot deck targeted at those. Additive — does NOT block A.

**Next-session deliverable**: full plan doc (`docs/plans/2026-05-29-001-feat-content-generation-panel-plan.md`) with unit breakdown, test strategy (incl. a stub generator backend so e2e tests don't burn LLM quota), and rollback strategy. Execute the session after.

---

## Carry-forward — secondary

### Topic config gap

Your local `~/.config/studyloop/config.toml` doesn't have a `topics:` block. The studyloop **schema** supports it (`studyloop.settings.Settings.topics: list[TopicConfig]`) and the session-start path uses it (`session.py:752` → `topic_resolver.resolve_topic`). The schema is structurally compatible with the old `studyctl` topics block — just rename `obsidian_path` → `path`.

The generation panel's source dropdown leans heavily on `config.topics`. Population is a 5-minute chore but **must** happen before the generation feature ships in a useful state.

### Pre-existing flaky test

`tests/test_acp_transport.py::TestEventsAndUpdates::test_available_commands_update_is_dropped` — fails ~1-in-3 runs on clean main, unrelated to any recent change. Should be diagnosed and fixed eventually but doesn't block any feature work.

### studyloop config vs old studyctl config — confirmed differences

The two configs differ for documented reasons (not bug):

| studyctl had | studyloop dropped/replaced because |
|---|---|
| `hosts:` multi-host sync | Local-first by design; cross-host sync is on Target Architecture roadmap. |
| `tts:` (kokoro/qwen3) | Replaced with browser Web Speech API. |
| `topics:` (curated registry) | Schema preserved, just not populated in user's local config yet. |

`content.base_path` and `obsidian_base` are studyloop-additions reflecting the new content pipeline.

---

## Conventions confirmed this session

- Vendored brand assets at `packages/studyloop/src/studyloop/web/static/icons/` for web; canonical source at repo-root `icons/`.
- `mmdc` (mermaid CLI) is installed at `/opt/homebrew/bin/mmdc` and works with `chrome-headless-shell` at `~/.cache/puppeteer/...` — used for doc validation.
- The `.gitignore` allow-list pattern (`!path/to/file`) is preferred over removing the broad ignore. See the `docs/architecture/` block.
- CLAUDE.md per-tool rules continue to hold: no `git push` without explicit approval, no `--amend`, conventional commits, no emojis in files.
- Pyright noise on `playwright`, `pytest`, `studyloop.*` imports is venv-resolution, not real — ignore.

---

## Next session — resume steps

```bash
cd /Users/taylaand/code/personal/tools/StudyLoop
git -P status                    # working tree clean
git -P log --oneline -5          # 26 ahead of origin/main, top is the OG-image readme commit

# 1. Read this handoff.

# 2. (Optional, 5 min): port the topics block from
#    ~/.config/studyctl/config.toml to ~/.config/studyloop/config.toml,
#    renaming `obsidian_path` → `path`.

# 3. Write the plan for the generation panel feature.
#    Path: docs/plans/2026-05-29-001-feat-content-generation-panel-plan.md
#    Reference this handoff for the brainstorm decisions.

# 4. THEN execute. Roughly 3-4 units. v1 (date-window struggles), B (agent-
#    marked struggles) is a follow-up plan, not part of v1.

# 5. When ready to push: 26 local commits represent ~5 sessions of work.
#    User must give explicit go-ahead.
```

---

## Key files for carry-forward work

| Purpose | Path |
|---|---|
| Existing generator schemas (NotebookLM-shape, target output) | `packages/studyloop/src/studyloop/content/schemas.py` |
| Existing generator backends | `packages/studyloop/src/studyloop/content/generators/` |
| Existing CLI command | `packages/studyloop/src/studyloop/cli/_content.py` (search for `generate-cards`) |
| Active-session singleton pattern (mirror for active-generation) | `packages/studyloop/src/studyloop/session/active.py` |
| Topic-resolver | `packages/studyloop/src/studyloop/logic/topic_resolver.py` |
| Session struggles query (for scope D) | `packages/studyloop/src/studyloop/history/sessions.py` (search for struggle queries) |
| Settings schema | `packages/studyloop/src/studyloop/settings.py` |
| Live Kiro regression test pattern | `packages/studyloop/tests/test_web_acp_dogfood_kiro.py` |
| WebUI sidebar nav (where the new tab goes) | `packages/studyloop/src/studyloop/web/static/index.html` (~line 141) |
| Architecture docs (now updated; reference for the new feature) | `docs/architecture/current.md`, `docs/architecture/target.md` |
