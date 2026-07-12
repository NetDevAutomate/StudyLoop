# StudyLoop Comprehensive Review — 2026-07-11

**Method:** 9 domain reviewers (core-domain, web-backend, content-pipeline, frontend,
cli/tui/mcp, agent-session-tools, tests/ci, security, architecture/docs) + 2 design
strands (TTS, desktop MCP), every finding independently adversarially verified against
the code (44 confirmed, 11 refuted), plus a completeness-critic pass over areas the
reviewers didn't cover. 67 agents total.

**Branch caveat:** the review ran on worktree branch `worktree-fix-startup-errors`
(base `050e77b`). Every finding was re-checked against `main`; stale-branch
artifacts are marked as such.

**Update 2026-07-12 — reconciled against main HEAD `9f033fa`** ("stabilize session
picker and add grok support"). Main advanced 9 commits past this worktree's base and
independently closed several findings. §0 below is the authoritative live status;
the priority tables in §2 are the original review snapshot, annotated where main has
since moved. **My worktree's two startup fixes (`9a57577`) are now superseded** —
main fixed both the string-topics loader (more completely, via `_topic_from_raw`) and
the bedrock `UnboundLocalError` (more completely, moving the boto3 import + disabling
IMDS). This worktree branch can be abandoned once §0's remaining items are picked up
on main; there is nothing here to merge except this document.

---

## 0. Live status against main HEAD `9f033fa` (2026-07-12)

### Fixed on main — close these

| Was | Where | Fixed by |
|---|---|---|
| String-topics loader crash (P0 #2a) | `settings.py` `_topic_from_raw` | `9f033fa` — full rewrite: string entries → name-only TopicConfig, non-dict → `ConfigError` with position, active topics capped at 3 (`MAX_ACTIVE_TOPICS`). Supersedes worktree `9a57577`. |
| Per-topic `obsidian_path` non-scalar crash (P0 #2c) | `settings.py` | `9f033fa` — `_topic_from_raw` guards the shape. |
| Bedrock `UnboundLocalError` on missing boto3 (this week's other startup crash) | `_catalog.py:_bedrock_credentials_available` | `9f033fa` — boto3 import hoisted, `except NoCredentialsError` then `except Exception`, plus IMDS-probe disable to avoid slow credential resolution. Supersedes worktree `9a57577`. |
| Codex exporter regression (rated critical on this branch) | `exporters/codex.py` | `cc8b367`. |
| Dead GEMINI.md / AGENTS.md symlinks (P1 #5-arch, #42) | repo root | `5ea6dfa`. |
| OpenVox TTS backend absent | `speak.py`, `doctor/voice.py` | `732c53d` — `_speak_openvox`, registered `voice` doctor category, config keys, docs. |
| No active-topic-count doctor check | `doctor/config.py` | `9f033fa` — `check_active_topic_limit` warns past 3 topics and validates `topics` is a list. |

### Still open on main HEAD — confirmed present in `9f033fa`

Re-verified by reading main HEAD's source, not the worktree:

- **P0 #1 — topic→path traversal.** `session_dir_name` (`web/services/session_start.py`)
  still does `topic.lower().replace(" ", "-")[:20]` with no `/`/`..` strip, and
  `_start.py:562` still hand-rolls the same slug. **Unfixed. Highest priority.**
- **P0 #2b — `resolve_study_dirs()` + nested sections.** `settings.py:385` still does
  `raw.get("review", {}).get("directories")` → `AttributeError` on a bare `review:`
  key; `study_paths` as a bare scalar string still explodes into one Path per
  character (`content` loader, ~line 567). The topic loader was hardened but the
  *other* sections weren't. **Unfixed.**
- **P0 #3 — CI e2e coverage.** `ci.yml:104` `browser-smoke` still runs only
  `just test-browser-smoke` (the 9-test subset). **Unfixed.**
- **P0 #4 — kiro exporter** `_extract_text` still `continue`s on non-dict history
  entries (`exporters/kiro.py:158`). **Unfixed.**
- **P0 #5 — scrubber** `aws_secret_key` regex still requires quotes (`scrubber.py:26`).
  **Unfixed.**
- **P1 #13 — `doctor/database.py`** still imports the non-existent
  `agent_session_tools.config` (masked by broad `except`). **Unfixed.**
- **P1 #14 — `sw.js:24`** top-level `return;` SyntaxError still present. **Unfixed.**
  (See §0.1 — recommend deleting, not fixing.)
- **P1 #15 — `write_raw_config`** still `write_text` with no chmod; `lan_password`
  world-readable. **Unfixed.**
- All remaining agent-session-tools findings (#6 gemini FK, #7 aider dupes),
  generation-pipeline (#8 retry order, #9 max_tokens), async hygiene (#10–#12, #20,
  #21), and the P2/P3 lists are untouched by `9f033fa` (it only touched the picker,
  settings topic loader, bedrock detection, and grok support). **All still open.**

**Net:** of the 5 P0s, main closed one (#2a — the string-topics half of the settings
cluster). The traversal bug, the rest of the settings-shape cluster, CI e2e, and both
exporter-integrity P0s remain. The remediation plan in §3 stands, minus Step 2's
topic-loader portion.

### 0.1 Decisions (2026-07-12)

**TTS default → keep `kokoro`.** Confirmed. Rationale: local kokoro-onnx gives ~1.5s
TTFA vs OpenVox's measured 2.9–3.8s warm (10–12s cold), needs no separate app running,
and works identically on Linux dev boxes. OpenVox stays the *opt-in* macOS backend
(`tts.backend: openvox`) it already is on main — the right call for the latency-
sensitive live-narration path. This **supersedes the review's earlier `auto`-default
suggestion** (§5), which assumed warm latency would prove competitive; the benchmark
says it doesn't. Main's `732c53d` already ships `backend: kokoro` as default, so
**no code change needed** — only two cleanups remain: unify the OpenVox default voice
from `af_bella` to `am_michael` for cross-backend parity, and add a `tts` block to
`agent_session_tools.config_loader.DEFAULT_CONFIG` so partial `tts:` overrides
deep-merge instead of relying on scattered `.get(k, hardcoded)`. Main's own roadmap
note (in `docs/superpowers/plans/2026-06-01-...md`, added by `9f033fa`) independently
states the same policy: "voice output browser/Kokoro-first ... OpenVox is a good
optional backend for macOS terminal and MCP recap flows."

**PWA offline (`sw.js`) → delete it, don't finish it.** Recommendation: **low value,
remove the file and the manifest's implied offline promise.** Reasoning:

- *It has never worked.* `sw.js:24` is a hard SyntaxError and nothing ever calls
  `navigator.serviceWorker.register()` — there is no registration path anywhere in
  the JS. The PWA has shipped with zero service worker for its entire life; no user
  has offline support today, so removing it regresses nothing.
- *The offline use-case is thin for this app.* StudyLoop's core surfaces are inherently
  online-relative-to-a-local-server: the review PWA talks to `studyloop web` on
  localhost/LAN, generation calls LLM providers, session start drives a live agent.
  The one genuinely offline-capable surface — reviewing already-generated flashcards —
  is a narrow slice, and the device is almost always on the same LAN as the server
  that's serving the cards anyway. "Study flashcards on the train with the laptop
  closed" is the only real scenario, and it competes with the browser-Kokoro model
  cache (the *actually* valuable thing `sw.js` is currently written to preserve).
- *Finishing it has real cost.* A correct service worker means a cache-versioning
  discipline (this repo already has a documented history of stale-install bugs masking
  fixes — a mismanaged SW cache is exactly that failure mode, permanently, in every
  user's browser), a registration + update-prompt flow, and offline-state UI. That is
  a multi-day feature with an ongoing maintenance tax, for the train-flashcards slice.
- *The lazy correct move:* delete `sw.js`, drop the `sw.js` line from the caching
  discussion in `voice-output.md`, and keep the browser-Kokoro model in `Cache
  Storage` (transformers.js manages that cache itself — it does **not** need a service
  worker; the SW today only *spares* that cache on its self-destruct path, which is
  moot once the SW is gone). If offline flashcard review becomes a real request later,
  build it deliberately as its own scoped feature with cache-versioning baked in from
  the start — not by resurrecting a stranded file.

  *If you'd rather keep the door open:* the minimal alternative is to leave `sw.js`
  deleted but add a one-line `// PWA offline: intentionally not implemented — see
  audit 2026-07-11 §0.1` where registration would go, so the next person doesn't
  re-strand a half-built worker. Either way the SyntaxError file should not stay in
  the tree.

---

## 1. Overall assessment

The codebase is in **good health for its threat model** (single-user, local-first,
optional LAN). Strengths confirmed by reviewers and verifiers:

- Path-traversal guards are careful and consistent on disk-facing web routes
  (`explorer.py`, `artefacts.py`, `content/scope.py` all do `resolve()` +
  `is_relative_to()`), and `mcp/tools.py`'s `_safe_course_dir` was empirically
  verified to reject `..` and absolute-path injection.
- `secrets.py` is genuinely well-designed: Fernet + HKDF, 0600/0700 perms, atomic
  writes, corrupt-store fallback, values never returned via any query API.
- `yaml.safe_load` everywhere, no eval/exec/pickle, parameterized SQL throughout,
  WAL + busy_timeout via a shared `connect_db()`, narrow pre-accept WebSocket origin
  checks.
- The XSS defense for LLM/agent-derived content (marked → DOMPurify →
  anchor-hardening) was attacked with script/onerror/`javascript:` payloads in a
  jsdom simulation and held.
- FCIS separation (logic/ pure, shell thin) is real, and the services layer keeps
  framework imports out.
- Test infrastructure is strong: isolated-config fixtures, real behavioral
  assertions, dedicated permission/exception tests for secrets.

The problems cluster in five themes:
1. **The settings loader is systemically fragile** — the two startup crashes fixed
   this week were symptoms of a pattern, not isolated bugs.
2. **One security defect repeated three times** — unsanitized topic → filesystem
   path in every session-start transport.
3. **Async hygiene** — blocking I/O on the event loop in the session/ttyd/explorer
   paths.
4. **Exporter format-coverage debt** in agent-session-tools (the codex regression
   class).
5. **Doc/CI drift** — things documented but not enforced, or shipped but not
   documented.

---

## 2. Confirmed findings (44) — by priority

Severity reflects impact within the single-user/LAN threat model. Every item was
adversarially verified; "verify:" notes are from the verifier, not the reviewer.

### P0 — fix now

| # | File | Finding |
|---|---|---|
| 1 | `web/services/session_start.py:15` + `web/routes/session/_start.py:562` + PTY path | **Path traversal via `topic`** in `POST /api/session/start`: `topic.lower().replace(" ", "-")[:20]` never strips `/` or `..`. Verified to create directories outside SESSION_DIR. Same defect independently implemented in all three transports (PTY, ACP, legacy ttyd) instead of reusing `content.storage.slugify`. On LAN mode this is remotely reachable (post-auth). |
| 2 | `settings.py` loader (multiple) | **Systemic shape-fragility**: (a) `content.study_paths` as a bare scalar explodes into one `Path` per character (verified); (b) six nested sections (`review:`, `notebooklm:`, etc.) crash on present-but-non-dict values; (c) per-topic `obsidian_path: true` crashes instead of the graceful skip. Same class as this week's two startup crashes. |
| 3 | `.github/workflows/ci.yml` | **291 of 300 e2e-marked tests never run in any CI workflow** — `browser-smoke` runs a hardcoded 9-test subset. The layout-regression suite CONTRIBUTING.md names is never executed by CI. |
| 4 | `exporters/kiro.py:158` | `_extract_text` handles only dict-shaped history entries — **silently drops ~19% of real Kiro conversations' content** (verified against live data shapes). |
| 5 | `scrubber.py:25-27` | `aws_secret_key` regex requires quotes around the value — **misses the most common leak shape**: unquoted `AWS_SECRET_ACCESS_KEY=...` env-var assignment (verified live miss). |

### P1 — correctness bugs with a real trigger path

| # | File | Finding |
|---|---|---|
| 6 | `exporters/gemini.py:59` (+3 siblings) | Incremental re-import DELETEs messages before re-insert; once `session_clean` has scrubbed that session the DELETE raises IntegrityError (FK from scrub_log) which is silently swallowed → **scrubbed sessions stop updating forever**. Verified by empirical reproduction against the real schema+migrations. |
| 7 | `exporters/aider.py:158,182,202` | Message IDs are fresh `uuid4()` per parse with no delete-before-reinsert → **every incremental export duplicates all prior messages**. Only exporter with this gap. |
| 8 | `content/generators/openai_compat.py:244-256` | Retry history is built out of chronological order — **2nd+ retry sends a corrupted conversation** (correction turns misplaced). Verified by tracing `call_with_correction` end-to-end. |
| 9 | `content/generators/anthropic_compat.py:301` | `max_tokens` fixed at 4096 regardless of `count` (user can request 50 quiz questions) → silent truncation → schema-validation failure on large decks. |
| 10 | `web/routes/session/_start.py:55` | Legacy ttyd start path runs ~1.2s of `time.sleep`/subprocess **synchronously on the event loop** per request. |
| 11 | `web/routes/session/_ipc.py:12-44` | `tmux has-session` + `ps` subprocess calls run synchronously inside the async SSE polling loop — periodic event-loop stalls during live sessions. |
| 12 | `web/routes/explorer.py:594` | `explorer_search` holds a `threading.Lock` across a full filesystem walk + FTS rebuild inside a sync handler — slow searches serialize and stall workers. |
| 13 | `doctor/database.py:24` | Imports `agent_session_tools.config` — **module doesn't exist**; the check silently reports wrong results via broad except. |
| 14 | `web/static/sw.js:24` | Top-level `return;` is a **SyntaxError — sw.js fails to parse in every browser**. Currently latent (nothing registers the SW), which means the PWA has no service worker at all: `manifest.json` + docs claim installable PWA, but offline/install behavior is dead. |
| 15 | `settings.py:391` + `cli/_setup.py:169` | `config.yaml` can hold `lan_password` in plaintext and both writers use `write_text` with **no chmod** → world-readable by default umask, right next to the carefully-0600'd secrets store. |
| 16 | `secrets.py:303` | `logger.debug` logs the **first 6 chars of the raw secret** on every `set_secret`. |
| 17 | `state.py:109` + `sync.py:131` | `path.relative_to(Path.home())` crashes with ValueError for any obsidian_path outside `$HOME` (e.g. an external volume). |
| 18 | `state.py:61` | `state.json` written non-atomically (sibling `secrets.py` already has the correct temp+rename pattern to copy). |
| 19 | `scripts/smoke-installed-cli.sh:84` | Doctor-JSON validator's allowlist `{pass,warn,info}` is missing `fail` — a legitimately failing doctor check crashes the smoke script with a confusing "invalid status" instead of a real report. |

### P2 — degraded UX / debt with concrete consequence

| # | File | Finding |
|---|---|---|
| 20 | `web/routes/session/_ws.py:157-164` | Any transient WS disconnect (sleep/wake, tab reload) **kills the running agent** — `finally: session_active.release()` with no re-attach path. |
| 21 | `content_gen/_jobs.py:76` | Per-job asyncio.Queue leaks forever if the client never opens the progress WebSocket. |
| 22 | `index.html:1740-3438` | ~1700 lines (~49% of the file) of Alpine component logic inline with **zero test coverage**, duplicating the module pattern `components.js` already does right. |
| 23 | `index.html:1225-1235` | Model `<select>` uses nested `<span x-show>` inside `<option>` — the exact anti-pattern a comment 3 lines above warns against (options flatten children; broken labels). |
| 24 | `web/routes/session/_start.py` | 650-line file re-implements ~150 lines of orchestration that `session/start.py` exists to centralize, duplicated ~3× internally — this duplication is *why* the traversal bug (#1) exists three times. |
| 25 | `mcp/tools.py:200` | `get_chapter_text` has no lower-bound check; `chapter=0` matches `*ch00*`-adjacent globs and can silently return the wrong PDF. |
| 26 | `parking.py:36` | Migration failures swallowed by bare `except Exception: pass` — no log line at all. |
| 27 | `doctor/harness.py:30` | One unreadable steering file blanks the whole harness doctor category (no per-file error isolation). |
| 28 | `content/generators/bedrock.py:93` | Fallback-client construction only catches `CardGenerationError`; the bearer-token fast path can raise raw boto3 errors, breaking the documented all-errors-wrapped contract. |
| 29 | Coverage/CI | Coverage measured in CI but never gated; shellcheck recipe exists but never runs in CI; bandit skip-list duplicated verbatim between pre-commit and ci.yml; secret-scanning hooks are opt-in local only, never CI-enforced. |
| 30 | `explorer.py:371` | FTS index uses bare `sqlite3.connect()`, bypassing the project's own `connect_db()` WAL/busy-timeout contract. |

### P3 — docs & hygiene

| # | File | Finding |
|---|---|---|
| 31 | `docs/mcp.md` | The canonical "MCP Integrations" doc **never mentions studyloop-mcp** — the higher-value server (13 tools) is undocumented; only session-db-mcp appears. |
| 32 | `agents/mcp/README.md` | Tool table lists 10 tools; code has 13 (`end_session`, `record_topic_progress`, `log_topic` missing). Still stale on main. |
| 33 | `agents/*/mcp.json` | Every checked-in agent mcp.json hardcodes `/Users/ataylor/...` absolute paths (a previous machine's username). Verifier's sharper read: these files are **dead/orphaned artifacts** — nothing on the working code path consumes them. Delete or template them. |
| 34 | `docs/roadmap.md:105,117` | Claims PyPI OIDC publishing and release.yml/CHANGELOG are done — **no release.yml, no CHANGELOG.md exist** (cliff.toml does). |
| 35 | `docs/web-ui-guide.md:187` | Describes browser-neural-tts as gated behind an unmerged worktree; it merged long ago. |
| 36 | `docs/setup-guide.md:129` | `bedrock` extra documented as opt-in but the workspace dev-group makes boto3 always-on for contributors, masking the extra boundary. |
| 37 | `tests/test_mcp_log_topic.py:81-90` | Dead `patch(...) if False else patch(...)` block executing a no-op `pass`. |
| 38 | `tests/test_exporter_claude.py:12` | Stale "Known bug" docstring describing a bug that's already fixed. |
| 39 | `_start.py:628` | ttyd LAN credentials re-read from settings independently of what `create_app()` was launched with — flag-provided credentials diverge from what ttyd enforces. |
| 40 | `style.css` | 3514 lines/78KB single file (has section banners; needs a split plan only if it keeps growing). |
| 41 | `tts-engine.js:349` | `_probeSpeed()` tier-demotion threshold logic has zero test coverage. |
| 42 | root `AGENTS.md` | Diverged from canonical `agents/codex/AGENTS.md` (stale schedule-blocks reference) — fixed by `5ea6dfa` on main; this worktree predates it. |

### Fixed on main already (stale-branch artifacts — no action beyond rebase)

- **codex exporter regression** (was rated critical on this branch) → fixed by `cc8b367`.
- **GEMINI.md/AGENTS.md dead symlinks** → fixed by `5ea6dfa`.
- Worktree branches should be cut from up-to-date main; this one predates 8 commits.

### Notable refuted findings (so they don't get re-reported)

- `write_raw_config` dumping Path objects as unsafe YAML tags: real *latent* hazard,
  but no current call site ever passes a Path — downgraded to defensive hardening.
- ttyd WS proxy forwarding the browser's Authorization header: intentional/benign in
  context.
- Ollama 429/503 no-retry: documented, deliberate, and locked in by tests.
- explorer_tree cache race: benign — fingerprint check makes the race harmless.
- `session_clean` "silently swallowed" partial write: nothing is swallowed; sqlite
  rolls back uncommitted work on close and the exception propagates as a tool error.

---

## 3. Remediation plan

Ordered, each step independently shippable. (1) and (2) are this week's work.

**Step 1 — kill the traversal class (P0 #1, #24 together).**
Extract one `session_dir_slug(topic) -> str` into `web/services/session_start.py`
built on `content.storage.slugify` + an allowlist, and route all three transports
through it. This is the root-cause fix: one guard in the shared function, not three
patches. Add a regression test that posts `topic="../../../etc"` to
`/api/session/start` for each transport. *(~half day incl. tests.)*

**Step 2 — harden the settings loader once (P0 #2, plus improvement I1).**
Add a tiny `_section(raw, key) -> dict` helper (returns `{}` unless value is a
dict) and a `_str_list(value)` coercer; apply to all six nested sections and
`study_paths`; guard per-topic `obsidian_path` type. Then add the **round-trip
property test** (write_raw_config → load_settings for every section, including
hostile shapes) so this class of bug can't recur. Also: chmod 0600 in
`write_raw_config` (P1 #15) — one line, same file. *(~1 day.)*

**Step 3 — exporter integrity sweep (P0 #4, #5; P1 #6, #7).**
(a) kiro `_extract_text`: handle string entries; (b) scrubber: add unquoted
env-var-assignment pattern; (c) shared fix in `base.py` for the
delete-before-reinsert FK failure (delete scrub_log children first, or ON DELETE
CASCADE in a migration); (d) aider: stable message IDs + delete-before-reinsert like
its siblings. Add the improvement item I9: a `just verify-exporters` live-data smoke
(run `export_all` against real `~/.<tool>` dirs when present, assert non-zero adds) —
this is the check that would have caught the codex regression. *(~1–2 days.)*

**Step 4 — generation-pipeline correctness (P1 #8, #9, #28).**
Fix openai_compat retry-history ordering (verified trace shows exactly where);
scale `max_tokens` with count (`base + per_item * count`, capped); widen bedrock's
fallback except. All three have existing test files to extend. *(~1 day.)*

**Step 5 — async hygiene (P1 #10, #11, #12; P2 #20, #21).**
Wrap ttyd start in `asyncio.to_thread`; same for the SSE tmux-liveness probe (or
cache it for N seconds); move explorer FTS rebuild off-lock/off-loop
(`run_in_executor`, rebuild outside the lock, swap under it). For #20, smallest
viable fix: a grace window (e.g. 10s) before `release()` on WS disconnect so
reloads/sleep-wake re-attach. Queue leak (#21): TTL-expire queues never attached.
*(~2 days.)*

**Step 6 — CI honesty (P0 #3; P2 #29).**
Add a scheduled/nightly job running the full `-m e2e` suite with Playwright deps;
add `fail` to the smoke script's allowlist (#19); gate coverage at current baseline;
run `pre-commit run --all-files` in CI (kills the bandit-skip-list duplication and
enforces secret-scanning); add `just shellcheck` to CI. *(~1 day.)*

**Step 7 — small fixes batch (P1 #13, #14, #16, #17, #18; P2 #25–#27, #30).**
Each is minutes: fix the dead import, **delete `sw.js`** (decided §0.1 — PWA offline
is dead code, not a feature to finish; drop the `sw.js` reference in voice-output.md
too), drop the
secret slice from the debug log, guard `relative_to`, atomic state write, chapter
lower-bound, log the swallowed migration error, per-file isolation in the harness
doctor, use `connect_db()` in explorer. *(~1 day for all.)*

**Step 8 — docs truth pass (P3 #31–#36, #38, #42).**
One PR: document studyloop-mcp in docs/mcp.md, fix the tool table, fix roadmap
claims, fix the web-ui-guide TTS note, delete/template the orphaned agents/*/mcp.json,
update the stale docstring. *(~half day.)*

---

## 4. Improvement plan (not bugs — leverage)

Verified-against-code improvement items, in payoff order:

1. **Settings round-trip property test** (bundled into Step 2) — converts a
   recurring crash class into an impossible one.
2. **Exporter live-data smoke check** (bundled into Step 3) — "registered + green
   tests ≠ works on real data" is now a twice-learned lesson.
3. **Consolidate session-start orchestration** — after Step 1's tactical fix, move
   the three web transports onto `session/start.py` properly; deletes ~300 duplicated
   lines and makes the persona/DB/topic logic single-source. *(1–2 days, do after
   Step 1 has soaked.)*
4. **Extract inline Alpine components from index.html** into `components.js`
   modules (the pattern already exists and is already tested there); target: the 8
   factories/stores identified (generatePanel 315 lines, sessionTimer 290, …). Makes
   the frontend testable and reviewable. *(2–3 days, mechanical.)*
5. **CLI-docs consistency test** — walk the LazyGroup registry, assert every command
   appears in docs/cli-reference.md (same idea as the existing MCP/web parity test).
6. **Shared `write_config_to(path, data)`** — three hand-rolled yaml.dump sites in
   shared.py/_setup.py duplicate write_raw_config.
7. **Doctor manifest caching** — reuse `doctor/updates.py`'s TTL file-cache for the
   GitHub manifest fetch so `doctor` runs offline/fast.
8. **SESSION_DIR isolation helper** in tests/_helpers.py — three files hand-roll it.
9. **`_configure_gemini` idempotency test** + JSON-parse check instead of substring.
10. **lan_password threat-model note** in settings.py/secrets.py docstrings —
    make the "config.yaml is NOT the encrypted store" boundary explicit.

---

## 5. TTS design: OpenVox on macOS, browser/Kokoro everywhere else

**Reality check first:** `main` already ships the first cut of this
(`732c53d`): `speak.py` has `_speak_openvox()` (urllib → temp WAV → afplay),
`tts.backend: openvox` config keys, a registered `doctor` voice category with an
OpenVox reachability probe, and docs. The design work below reconciles the
research-strand report with what exists.

**Verified facts (live probes this session):**
- OpenVox app listens on `localhost:8000`, OpenAI-compatible:
  `POST /v1/audio/speech {"model":"kokoro","input":…,"voice":"am_michael"}` →
  `audio/wav` 16-bit PCM mono 24 kHz. `GET /v1/models` lists kokoro (54 voices),
  omnivoice (293), qwen3-tts-medium (148), chatterbox-turbo-medium/small (37).
  No REST voice-list endpoint (404 on all variants) — voice IDs must be curated
  or fetched via OpenVox's MCP tools.
- **Latency: ~10–12s cold, but 2.9–3.8s warm** (4-call steady-state benchmark run
  this session). Warm OpenVox is usable for recap/teaching-moment narration;
  still ~2× slower than local kokoro-onnx (~1.5s TTFA) for rapid interactive turns.
- **Voice namespace is shared**: OpenVox's kokoro model uses the exact same IDs
  (`am_michael`, `af_heart`, `bf_emma`…) as browser Kokoro and speak.py — **no
  mapping layer needed**. (Main currently defaults `openvox_voice: af_bella`,
  diverging from the `am_michael` default elsewhere — unify.)

**Recommended target (one design) — updated per §0.1 decision:**
- **CLI/server:** **keep `kokoro` as the default** (decision 2026-07-12; supersedes
  the `auto`-default idea originally floated here). The measured warm latency (2.9–3.8s
  vs local kokoro-onnx's ~1.5s) is too slow for the live-narration path to auto-prefer.
  Main already ships `backend: kokoro` default with `_speak_openvox` as the opt-in
  `backend: openvox` macOS path — **this is the target; no backend-resolution change
  needed.** Optional future nicety, not now: if a user explicitly opts into OpenVox,
  a response-shape-validated `/v1/models` probe (check `owned_by == "openvox"` to
  avoid a port-8000 dev-server false positive) before the first call would give a
  cleaner "OpenVox not running" message — but that's polish for the doctor check, not
  a default change.
- **Browser (all platforms including Mac):** keep the existing three-tier
  Kokoro engine (`neural-webgpu → neural-wasm → web-speech`) unchanged. **Do not
  build a server-proxied `/api/tts` for the Mac browser** — 3s+ per utterance vs
  sub-second warm browser-Kokoro, an offline-fragility dependency on a running app,
  and a second browser code path, all to deliver the same Kokoro voice family the
  browser already synthesizes. Revisit only if OmniVoice/Qwen3 voices in-browser
  become a real want.
- **Deprecate `qwen3`/ltts backend** (30–60s latency, `uvx` subprocess) — superseded
  by OpenVox's `qwen3-tts-medium`; map old config to a deprecation warning +
  fallback, don't hard-error.

**Gaps in main's current implementation to fix (the actual work remaining):**
1. ~~`auto` backend resolution~~ — dropped per §0.1 (keep `kokoro` default).
   Optional only: response-shape-validated `/v1/models` probe for a cleaner
   "OpenVox not running" doctor message when `backend: openvox` is set.
2. Unify default voice (`am_michael`) across openvox/kokoro paths.
3. `agent_session_tools.config_loader.DEFAULT_CONFIG` has no `tts` key — add the
   schema so deep-merge works instead of scattered `.get(key, hardcoded)`.
4. Replace `afplay` temp-file playback with the existing `sounddevice` path (reuse
   the 24→48 kHz resample that fixed crackling in `_speak_kokoro`) — or keep afplay
   but add a Linux guard message (afplay is macOS-only, consistent with the
   platform gate).
5. Tests without OpenVox in CI: `respx`-mock `/v1/models` (probe) and
   `/v1/audio/speech` returning a committed ~100KB fixture WAV recorded once from
   the real app (same offline pattern as `test_openai_compat_generator.py`).
6. Browser polish (small, same PR series): iOS Safari AudioContext unlock-gesture
   guard + toast; surface `tts:tier-change` to a visible toast when demoted to
   `web-speech`/`silent` (today it's console-only, invisible to the user).
7. Docs: voice-output.md already covers OpenVox config; add the auto chain +
   licensing/distribution note for OpenVox (provenance currently undocumented).

**Open questions:** whether OpenVox's `stream: true` actually streams (curl couldn't
distinguish; test with `httpx.stream()` TTFB before building anything on it);
OpenVox licensing/distribution before docs recommend installing it.

---

## 6. Desktop MCP design: Claude Desktop + Codex

Existing surface: **studyloop-mcp** (13 tools: list_courses, get_study_context,
record_study_progress, generate_flashcards, generate_quiz, get_chapter_text,
get_study_backlog, get_topic_suggestions, get_study_history, list_session_options,
end_session, record_topic_progress, log_topic) + **session-db-mcp** (7 tools, solid,
no changes needed) + a separate **study-speak** MCP server for TTS.

### What desktop apps CAN do
- **Claude Desktop:** stdio servers via `claude_desktop_config.json`; tools, MCP
  **prompts** (surfaced as selectable templates), and **resources** (attachable);
  remote servers via Connectors. SDK in use (`mcp[cli] 1.26.0`) supports
  `@mcp.prompt()` / `@mcp.resource()` — the codebase just never uses them.
- **Codex:** `~/.codex/config.toml` `mcp_servers`; tools solidly. **Prompts and
  resources support is unverified — test against the real app before building
  anything that depends on them** (tools must remain the fallback path).

### What they CANNOT do (the honest impossible-list)
| Impossible | Nearest approximation |
|---|---|
| Embedded PTY/tmux terminal in chat | None for the terminal; the *session content* is replicable via prompt+tool loop below |
| WS/SSE push (generation progress, live activity) | Synchronous tool that blocks to completion, or job_id + agent-initiated polling |
| TTS audio playback in the chat bubble | Keep the separate study-speak MCP server — it plays on the machine's speakers alongside the chat |
| Pomodoro with real notifications | `pomodoro_status(start/check/stop)` tool the agent polls; prompt instructs it to check periodically |
| Custom UI (card-flip, Y/N/S keys, themes, OpenDyslexic) | Chat turns only; client controls all rendering |
| Writing provider API keys | Don't build it — secrets via chat is an anti-pattern |

### Coverage gaps that matter (why desktop feels thin today)
1. **No card-serving tool** — nothing returns actual due-card content; an agent can
   say "7 due" but cannot quiz. This is the single highest-value add.
2. **Zero Course Explorer surface** — no tree/read/search of lessons via MCP.
3. **No generation-pipeline trigger** — `generate_flashcards`/`generate_quiz` only
   save agent-authored JSON; nothing invokes the provider pipeline.
4. **No wins/streaks/teachback/bridges** (CLI-only) — the AuDHD
   positive-reinforcement surface is invisible to desktop users.
5. **No prompts/resources at all** despite full SDK support.

### Build plan (ordered, each step small + testable)
1. **Explorer read-parity tools**: `get_lesson_tree`, `read_lesson(lesson_id)`,
   `search_lessons(query)` — pure wrappers over explorer.py internals, reusing the
   `_safe_course_dir` guard. Test with the existing `test_mcp_session_parity.py`
   shape-parity technique.
2. **Card-serving**: `get_due_cards(course, limit, kind)` returning full card
   bodies (join `get_due()` hashes with `review_loader` — extract that join into
   `services/review.py` so CLI/web/MCP share it), and
   `submit_card_answer(...)` returning updated SM-2 state (next interval) so the
   agent can tell the user when the card returns.
3. **Insight parity**: `get_wins`, `get_streaks`, `record_teachback`,
   `mark_struggling(course, section, publisher)` (log_topic loses provenance) —
   one-line wrappers.
4. **MCP prompts**: `start_socratic_session(topic, energy)` (reuses
   `build_canonical_persona` — the persona delivery mechanism desktop apps lack —
   and bulk-loads due cards + struggle history so the agent needs zero warm-up
   calls) and `review_due_deck(course)` (instructs the turn-by-turn quiz loop:
   agent presents front → user answers in chat → *agent judges* → calls
   submit_card_answer → relays the new interval). Spike against MCP Inspector first;
   prompt return shapes are easy to get subtly wrong.
5. **Generation**: `list_generatable_sources`, `generate_deck_from_source(...)`
   run-to-completion synchronous (test against the Stub provider only).
6. **Resources** (Claude-Desktop-first): `studyloop://lesson/{provider}/{course}/{slug}`
   and `studyloop://deck/{course}/{kind}` — hold until Codex resource support is
   verified; tools from steps 1–2 remain the universal fallback.
7. **Docs**: add the missing studyloop-mcp section to docs/mcp.md with
   Claude Desktop (`claude_desktop_config.json`) and Codex (`config.toml`) install
   snippets, plus the honest capability matrix.

**How review feels in chat** (set expectations in docs): no flip animation, no
keyboard shortcuts, LLM-graded rather than exact-match, no timing — but a genuinely
usable Socratic review loop, and uniquely better than the web UI in one way: the
agent can *explain* a miss immediately, in context, and log it as a struggle with
provenance.

---

## 7. Where we are

- **Done:** review complete; 44 confirmed findings triaged; reconciled against main
  HEAD `9f033fa` (§0); both design strands settled.
- **Decisions made (2026-07-12, §0.1):** TTS default stays **`kokoro`** (OpenVox
  opt-in on macOS — no code change, already the state on main); PWA offline `sw.js`
  is **dead code to delete**, not a feature to finish (near-zero value, never worked,
  real maintenance tax if resurrected).
- **Fixed on main since the review** (§0): string-topics loader, bedrock
  UnboundLocalError, codex exporter, dead symlinks, OpenVox backend, active-topic
  doctor check. **This worktree's `9a57577` startup fixes are superseded** — nothing
  here needs merging except this audit doc.
- **Next, highest-value first (all confirmed still-open on main HEAD):**
  1. Topic→path traversal — one shared `session_dir_slug()` on `slugify` (§3 Step 1).
  2. Finish the settings-shape hardening main *started* — `resolve_study_dirs` bare-
     `review:` crash + scalar `study_paths` char-explosion + the round-trip test
     (§3 Step 2, minus the topic-loader part main already did).
  3. Exporter integrity — kiro string entries, scrubber unquoted-AWS, gemini FK,
     aider dupes + the live-data smoke check (§3 Step 3).
  4. CI runs the full e2e suite (§3 Step 6); delete `sw.js` (decision above).
- **Open decision remaining:** when to land these on main (recommend small PRs
  straight onto main per §3, since this worktree branch is now superseded).
