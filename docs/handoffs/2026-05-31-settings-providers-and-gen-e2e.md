# Handoff — Settings/Providers panel + end-to-end generation validation

**Date:** 2026-05-31
**Branch:** `feat/settings-providers-panel` (4 commits ahead of `main`, tree clean)
**Machine note:** cannot push from here — dirsync to MacMini to push. Persistent
`.git/index.lock` from the cmux git-status hook; `rm -f .git/index.lock` + retry.

## What's DONE and committed (Phases 1–4)

| Commit | What |
|---|---|
| `547b4e0` | secrets: `AuthKind` taxonomy + `get_auth_kind`; `bedrock_bearer_token`/`ollama_base_url` store names; `provider_auth.py` (new): `test_bedrock_bearer` (minimal Converse, token scoped via `_with_bearer_env`), `test_ollama_generate` (quality bar: schema-valid + ≥1 card) |
| `ec476c5` | `provider_profiles.py`: bedrock+ollama now first-class in `PROFILES`; `bedrock.py` `_build_client` bearer fast-path (no profile/STS when `AWS_BEARER_TOKEN_BEDROCK` set); `job.py` `_maybe_inject_bearer`; `list_providers` rewritten from PROFILES (auth_kind + ollama base_url; no ad-hoc append) |
| `9c71747` | `_SECRETS_PROVIDERS` += bearer/ollama-url; `POST /api/content/providers/{slug}/test`; `_ollama_reachable` |
| `c1bef1a` | Settings sidebar panel + `settingsPanel()` Alpine component + style.css; **test-flow fixes** (below); Ollama model discovery |

**Backend is solid: 133 unit/route tests pass.** Verified live via curl + Playwright MCP:
- Settings panel renders all 7 providers with correct per-auth_kind controls.
- minimax/gemini/bedrock "Test" buttons work (empty key → falls back to stored key).
- Ollama test **discovers installed models** via `/api/tags` (found `gemma4:latest`, generated 5 cards). **Recommended Ollama model for this machine: `gemma4:latest`** (it's what's installed and it passed the quality bar).

## OPEN ISSUES (for the fresh fanout session)

### 1. ⚠️ Generation output not recognised by Quiz/Flashcard panels (USER-REPORTED, NOT ROOT-CAUSED)
User ran `gen-b7d3fc25` (8 tasks, 4 sources, bedrock) → neither panel showed the results.
- **Write path:** `job.py:_course_output_dir` → `base/<publisher>/<course>/{flashcards,quizzes}/<id>-flashcards.json` / `-quiz.json` (via `storage.get_course_dir`).
- **Read path:** `review_loader.discover_directories(config_dirs)` — only walks base + ONE level of children + a `downloads/` special-case (`review_loader.py:301`). `_has_review_content` checks `<dir>/flashcards/*flashcards.json`.
- **Prime suspect:** 3-level layout mismatch (same class as the vendor-dropdown bug fixed earlier in `41545c1`). Generation writes 3 levels deep (`base/CodeWithMosh/Complete_SQL_Mastery/flashcards/`), but `discover_directories` may not descend `publisher/course/`. ALSO: no `*-flashcards.json` files were found newly written under `~/Obsidian/Personal/Study` in the last 2h despite the job reporting 8 tasks — so EITHER the job wrote elsewhere (different `base_path`) OR the writes failed silently. **Confirm where the bedrock job actually wrote, and reconcile write-root vs read-root.** This is the highest-value bug.

### 2. 6 settings-panel e2e tests fail on a strict-locator issue (impl works; test is wrong)
`tests/test_web_settings_panel_e2e.py`. `x-show` leaves hidden auth-kind divs in the DOM, so `.provider-row` + `input[type=password]` matches across rows (strict-mode violation). The PANEL itself is verified working live. Fix the locators (scope to visible elements / use `.first` / target by unique placeholder), don't change the panel. The other e2e classes (nav, save-flow, test-states) pass.

### 3. NEW REQUIREMENT — per-provider model dropdown (Phase 5, not started)
User decision: **Settings + Generate panel BOTH use discovered models.**
- Each provider row + the Generate panel's model picker should list discovered models: Ollama = live `/api/tags` (reuse `provider_auth.list_ollama_models`); others = curated `PROFILES` models (already in the `/providers` response).
- Selected model persists per provider (proposed store key `model:<slug>`) and becomes the default the Generate panel pre-selects and generation uses.

### 4. NEW REQUIREMENT — end-to-end generation + quality workflow (the `/goal` the user wants)
Build a fanout workflow that, **looping until an Opus-4.8 judge approves**:
1. Selects provider + course + section, generates **5 cards/source for BOTH quizzes and flashcards**, for each of:
   - **AWS Bedrock — Claude Sonnet 4.6** (`us.anthropic.claude-sonnet-4-6-20251101-v1:0`)
   - **MiniMax M2.7**
   - **Ollama — `gemma4:latest`** (recommended; installed + passes quality bar)
2. All these end-to-end generations must complete **with no errors** (depends on Issue 1 being fixed first).
3. **Opus 4.8 judges** the quiz + flashcard quality (schema-valid is the floor; judge scores content quality).
4. A **Playwright e2e** then walks the full Quiz and Flashcard panels to validate they render and contain quality questions.

## Key files
- `packages/studyloop/src/studyloop/provider_auth.py` — bedrock/ollama tests + `list_ollama_models`
- `packages/studyloop/src/studyloop/secrets.py` — auth-kind, store, `test_provider_auth`
- `packages/studyloop/src/studyloop/web/routes/content_gen.py` — `list_providers`, `/secrets`, `/providers/{slug}/test`, `_ollama_reachable`/`_ollama_base_url`
- `packages/studyloop/src/studyloop/content/job.py` — `run_job`, `_course_output_dir`, `_maybe_inject_bearer`
- `packages/studyloop/src/studyloop/review_loader.py` — `discover_directories` (the read side — suspect for Issue 1)
- `packages/studyloop/src/studyloop/web/static/index.html` — `settingsPanel()` (~line 1733), Generate panel `generatePanel()`, nav store
- `docs/architecture/...`, plan at `~/.claude/plans/shimmering-moseying-perlis.md`

## Verify/run discipline (learned this session)
- Reinstall before any manual/e2e check: `uv tool install './packages/studyloop[web,bedrock,sessions]'` — `[bedrock]`-only DROPS web/sessions. Stale server = phantom bugs (empty Generate panel, "Network error" on test).
- Launch user's real path: `~/.local/bin/studyloop web --port 8567` (NOT a stub config, or publishers/courses are empty).
- e2e is `pytest.mark.e2e`, deselected by default; run with `-m e2e`.
- Full-suite baseline: `1 failed (test_terminal_proxy) + 35 errors (test_web_session_ws async-isolation)` — both pre-existing, pass in isolation. Don't chase them.
