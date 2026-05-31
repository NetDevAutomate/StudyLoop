# Overnight handoff — gen output fix + autonomous gen-quality workflow

**Date:** 2026-06-01 (overnight, unattended)
**Branch:** `feat/settings-providers-panel` (7 new commits ahead of last night's `b13bd80`)
**Machine note:** cannot push from here — dirsync to MacMini to push.

---

## TL;DR

- **Open Issue #1 (generated decks invisible to panels): FIXED & PROVEN.** It was
  TWO bugs, not the handoff's single "3-level" hypothesis. Decks now generate →
  land where the panels read → render in the Quiz/Flashcard UI (curl + Playwright
  confirmed).
- **Autonomous gen+judge+validate+report workflow: BUILT, LAUNCHED, COMPLETED.**
  Bedrock **APPROVED 9/9**, Ollama **APPROVED 8/7**, MiniMax **generates cleanly
  now (2 real adapter bugs fixed) but its quiz quality is below the Opus judge bar
  — a model limitation, not a code bug.**
- **Playwright validated all three** provider courses render in the panels (10
  flashcards + 10 quiz each).
- **Issue #2 (6 e2e selector failures): FIXED** — all 8 settings-panel e2e pass.
- **Issue #3 (model dropdown): DEFERRED** — see "Not done" below.

---

## What passed (DoD scorecard)

| DoD item | Status |
|---|---|
| Issue #1 fixed and proven (write/read path reconciled) | ✅ proven end-to-end |
| Bedrock generates 5+5 with zero errors, judge-approved | ✅ APPROVED 9/9 |
| Ollama generates 5+5 with zero errors, judge-approved | ✅ APPROVED 8/7 (4 rounds) |
| MiniMax generates 5+5 with zero errors | ✅ (after 2 code fixes) |
| MiniMax judge-approved quality | ❌ REJECTED 9/6 — model limitation, reported |
| Playwright confirms Quiz+Flashcard panels render quality content | ✅ all 3 courses |
| Final report committed under docs/handoffs/ | ✅ this + the workflow report |

**Tests:** every test file touching changed code is green (159 passed in the
targeted run). Full-suite baseline unchanged: the `test_web_session_ws` cluster
(35 errors in full-suite, **passes 11/11 in isolation**) and `test_terminal_proxy`
(deselected by default) are the documented pre-existing artifacts — not regressions.

---

## Open Issue #1 — root cause (corrected from the prior handoff)

The prior handoff hypothesised a single "3-level layout" mismatch. It was actually
**two independent bugs plus a misleading symptom**:

1. **Read-root never configured (dominant).** The panels read decks from the
   `review.directories` config key; the generator WRITES under `content.base_path`.
   The live `config.yaml` sets only `content`, so `_web.py` handed
   `discover_directories([])` → empty → panels showed nothing regardless of disk.
   **Fix:** new `settings.resolve_study_dirs()` falls back to `content.base_path`
   when `review.directories` is unset. Wired into `_web.py` + `mcp/tools.py`.
   (commit `976bed0`)
2. **Discovery only descended one child level.** The vault is 3 levels deep
   (`base/<publisher>/<course>/{flashcards,quizzes}/`); immediate children of the
   study root are *publishers*, not courses. **Fix:** recursive descent (depth 4),
   stopping at the first content-bearing dir; skips eagerly-mkdir'd empty deck
   dirs. (commit `976bed0`)
3. **The user's symptom artifact:** `Complete_SQL_Mastery/{flashcards,quizzes}/`
   existed but were EMPTY — `get_course_dir` mkdirs subdirs at job start, so empty
   dirs ≠ successful generation. The original bedrock job's tasks had failed
   silently (boto3 era). Resolved as part of the gen-pipeline work below.

**Proof:** `scripts/prove_gen_readpath.py` generates a real Ollama deck →
`resolve_study_dirs()` → `discover_directories` → `get_cards` returns 9 flashcards
+ 6 quiz Qs. Then via the live server: `/api/courses` lists the course,
`/api/cards` returns quality content, and Playwright confirmed the Flashcard panel
renders card 1/9.

---

## The autonomous workflow

`scripts/gen_quality_workflow.js` (commit `a8af7ce`) — a single background
Workflow with the judge-loop INSIDE the script:

- **phase 'Generate+Judge'** — 3 providers run concurrently via `parallel()` (one
  stuck provider never blocks the others). Each runs its own loop: generate 5
  cards/source for flashcards + quizzes → Opus-4.8 judge scores real content
  quality → approved? break : feed the judge's reasons into the next round's
  prompt and regenerate. Ceilings: max 4 quality rounds; a generation ERROR gets 2
  retries then FAILED; every loop guarded by `budget.remaining() > 100k`.
- **phase 'Validate'** — per-provider agent asserts `/api/courses` + `/api/cards`
  and drives Playwright MCP to confirm the panels render the decks.
- **phase 'Report'** — wrote `docs/handoffs/2026-06-01-gen-quality-workflow-report.md`.

Each provider writes to an isolated output course (`Complete_SQL_Mastery__<key>`)
so concurrent generation + the judge + Playwright never clobber each other. The
three courses are live in the panels now for visual comparison.

Run cost: 32 agents, ~2.2M subagent tokens, ~24 min wall-clock.

### Bedrock model-id correction (important)

The spec named `us.anthropic.claude-sonnet-4-6-20251101-v1:0`. That raw
foundation-model id is **not directly invokable** in this account
(`ValidationException: provided model identifier is invalid`). The cross-region
**inference-profile** id `us.anthropic.claude-sonnet-4-6` works and was used
throughout. The settings default already uses the correct form.

---

## MiniMax — two code bugs fixed, one model limitation remains

The workflow surfaced MiniMax failures. I root-caused and fixed the **code**:

1. **error 2013 → `tool_result` correction** (commit `2c26c2a`): the
   schema-correction retry appended a plain-text user turn after an assistant
   `tool_use`; MiniMax's strict `/anthropic` shim rejects that (Anthropic itself
   tolerates it). Now emits a protocol-valid `tool_result`.
2. **inline-XML tool calls** (commit `c4b2030`): MiniMax M2.7 intermittently emits
   the forced tool call as `<minimax:tool_call><invoke …><parameter …>` text
   markup instead of a native `tool_use` block (~half the time). Added a
   `_parse_inline_tool_call` fallback **and** a transient-retry in
   `call_with_correction` so a single bad emission no longer hard-fails. Plus a
   `--max-retries` knob (commit `209d0e4`) for flaky providers.

**Proven:** MiniMax data-types quiz (previously failed reliably) now generates
4/4 clean consecutive runs; a full two-section run wrote 4/4 files (20 cards).

**Still below bar (NOT code):** after clean generation, the Opus-4.8 judge
REJECTED the fresh MiniMax decks **9/6** — flashcards excellent, but the quiz had
`isCorrect` on the wrong option (a Workbench execution-scope confusion) and
rationale-to-option copy-paste mismatches. This matches the workflow's 3 in-loop
rejections. **MiniMax M2.7's quiz content quality is a model limitation.**

---

## What needs YOUR decision

1. **MiniMax rotation (the one real open product call).** The code is fixed —
   MiniMax no longer errors. But its quizzes don't clear the strict quality bar,
   while its flashcards are genuinely strong (judge score 9). Options:
   (a) keep MiniMax for **flashcards only**; (b) keep it for both and accept
   weaker quizzes; (c) drop it for quizzes. No code work needed for any choice.
2. **Issue #3 (per-provider model dropdown) — PARTIALLY ALREADY DONE; rest
   deliberately deferred.**
   - The **Generate panel already has a working model dropdown** (`index.html`
     ~L866, `form.model` ← `modelsForProvider` ← the providers response's
     `models[]`). So "Generate panel uses discovered models" is already true.
   - **Not done:** the per-provider `<select>` in the **Settings** panel + the
     `model:<slug>` persistence that pre-seeds Generate. The handoff itself called
     `model:<slug>` a *proposed* store key — that's a persistence-schema decision
     I declined to make unattended. Frontend-only once you confirm the key name;
     estimate ~1–2 h. Recommend a fresh session.
   - **⚠️ Related real finding (verify before relying on the Bedrock dropdown):**
     the curated Bedrock model IDs in `provider_profiles.py` are WRONG for this
     account. The dated foundation-model IDs
     (`us.anthropic.claude-sonnet-4-6-20251101-v1:0`,
     `...-haiku-4-5-20251001-v1:0`) both fail with `ValidationException: provided
     model identifier is invalid`. The inference-profile form
     `us.anthropic.claude-sonnet-4-6` WORKS (proven — it's what the workflow used
     and the settings default). But `us.anthropic.claude-haiku-4-5` ALSO fails —
     so the IDs are **account/region-specific and not guessable**. I deliberately
     did NOT "fix" the curated list because I could only empirically verify the
     Sonnet id. **Action for you:** run `aws --profile bedrock-prod bedrock
     list-inference-profiles --region us-east-1` (your SSO token had expired
     overnight) and update the curated Bedrock `models[]` to the real available
     profile IDs. Until then, a user picking Bedrock-Haiku in the dropdown will hit
     a ValidationException; Bedrock-Sonnet works.
3. **Ollama deferred nits** (approved, non-blocking): the judge flagged 4 quiz/
   flashcard improvements (connectivity-trivia card, a Workbench-UI quiz Q, a
   trigger-rationale fix, a DECIMAL(19,4) nuance). Accept as-is or queue a
   targeted regen.
4. **Bedrock ENUM/`ALGORITHM=INSTANT` gap** — judge noted a course-level
   simplification, not an error. Accept or add a follow-up card.

---

## Commits this session (on `feat/settings-providers-panel`)

```
209d0e4 feat(workflow): --max-retries knob on gen harness for flaky providers
c4b2030 fix(content): tolerate MiniMax inline-XML tool calls + retry transient gen failures
ba7ffd8 test(web): fix 6 settings-panel e2e strict-locator failures (Issue #2)
a8af7ce feat(workflow): autonomous generate+judge+validate+report across 3 providers
b03189f test(content): harness scripts for gen+read proof and workflow generation
2c26c2a fix(content): MiniMax quiz gen — send tool_result correction, not plain text
976bed0 fix(review): reconcile deck write-root with panel read-root (Issue #1)
```
(plus this handoff + the workflow report)

## Key files
- `packages/studyloop/src/studyloop/settings.py` — `resolve_study_dirs()` (read/write reconcile)
- `packages/studyloop/src/studyloop/review_loader.py` — recursive `discover_directories`
- `packages/studyloop/src/studyloop/content/generators/anthropic_compat.py` — MiniMax fixes
- `packages/studyloop/src/studyloop/content/generators/_retry.py` — transient-retry
- `scripts/gen_quality_workflow.js` — the autonomous workflow
- `scripts/gen_for_workflow.py` — per-provider generation harness (`--output-course`, `--max-retries`)
- `scripts/prove_gen_readpath.py` — Issue #1 end-to-end proof
- `docs/handoffs/2026-06-01-gen-quality-workflow-report.md` — full per-provider workflow report

## Verify discipline reminders (carried forward, all honoured tonight)
- Reinstall before any manual/e2e check: `uv tool install './packages/studyloop[web,bedrock,sessions]' --reinstall`
  (`--reinstall` is REQUIRED — a plain `install` served a stale build tonight and
  masked the fixes; cost ~10 min to spot).
- Real launch path: `~/.local/bin/studyloop web --port 8567` (server still running).
- e2e is `-m e2e` (deselected by default).
- Full-suite baseline: `test_web_session_ws` (35 errors in full-suite, passes in
  isolation) + `test_terminal_proxy` (deselected) — treat as green if only these.
