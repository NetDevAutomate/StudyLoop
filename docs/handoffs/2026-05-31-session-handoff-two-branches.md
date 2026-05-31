# StudyLoop — Fresh-Session Handoff (two active local branches)

**Created**: 2026-05-31 (afternoon) · **Repo**: local-only (no remote, never push) · **Default branch**: `main` @ `f720a21`

---

## TL;DR

Two independent feature branches exist locally, both off `main`. Pick up either:

1. **`feat/provider-key-entry`** (2 commits) — **COMPLETE & green.** The original "generate with a selected provider + add missing API keys, stored encrypted" feature now works end-to-end. Only optional CLI-parity polish remains. Ready to merge to `main` whenever you want.
2. **`feat/struggle-extraction-pipeline`** (11 commits) — **BLOCKED on a quality gate.** The struggle-extraction pipeline is built and tested, but the LLM extractor doesn't meet the precision/recall bar; the fix is to expand the golden label set (data, not code). See the dedicated doc below.

Nothing is pushed (local-only repo). Working tree is clean except gitignored extractor artifacts.

---

## Branch topology

```
main  f720a21  (docs(handoff): in-flight state — P0 stands)
 │
 ├── feat/provider-key-entry          [2 commits — COMPLETE]
 │     b7caf99  feat(web): Generate-panel inline API-key entry (#2)
 │     edead0d  fix(content): adapters + availability honour encrypted store (#1+#3)
 │
 └── feat/struggle-extraction-pipeline  [11 commits — BLOCKED on quality gate]
       dfb82bb  docs(handoff): P6 results + data-expansion path
       573a0bb  fix(extract): fuzzy concept matching + recall floor (P6)
       a564a22  feat(extract): hill-climber (P6)
       53238ae  test(extract): real-data live tests + error isolation (P4 hardening)
       fe5c03e  fix(extract): eval applies pre_filter (P4)
       68cfab6  feat(extract): LLM extractor (Bedrock Converse) + eval harness (P4)
       c6968e8  feat(extract): golden labels + split + topic vocab (P2)
       61126df  test(web): e2e struggling-topics dropdown (P3)
       868d9e9  feat(harness): wire extract-struggles into 4 session-ends (P5)
       44784d5  feat(extract): interface + stub + pipeline + CLI (P1)
       71e1cc4  feat(mcp): log_topic + CodexExporter (P0)
```

Recovery: the pre-split combined tip was `f618d51` (saved to `/tmp/struggle_tip.txt` during this session; ephemeral). Not needed — every commit now lives on exactly one branch.

---

## Branch 1 — `feat/provider-key-entry` (COMPLETE)

### What it delivers
The original feature, working end-to-end:
```
Select provider in the web Generate panel
  → if it has no key, an inline "needs API key" form appears
  → paste key → "Test & save" → backend tests it against the provider's auth endpoint
  → on success: stored ENCRYPTED in ~/.config/studyloop/secrets.bin, provider flips to enabled
  → at generation time the adapter reads the key back from the store and uses it
```

### The two commits
- `edead0d` (#1 + #3, backend): `anthropic_compat.py` + `openai_compat.py` `_read_api_key()` now call `secrets.get_secret(slug)` (resolves encrypted store → env var → None) instead of `os.environ` only. The `/api/content/providers` `available` flag now ORs the encrypted store with the env var. Bedrock's separate boto3-credential path untouched.
- `b7caf99` (#2, frontend): inline key-entry row in `index.html` (shown only for a keyed provider that isn't yet available; bedrock excluded), POSTs `/api/content/secrets` (test-then-store), re-fetches providers on success, shows verify/error feedback. Minimal CSS in `style.css`.

### Why this was needed (the original audit)
Commit `4c638f9` (on `main`) built a fully-tested encrypted store + secrets routes, but **nothing read from it and nothing wrote to it via the UI** — a sealed vault with no doors. `edead0d` added the read door (generation), `b7caf99` added the write door (UI).

### Verification (all green on this branch)
- Backend: 82 unit/integration tests (`test_secrets.py`, `test_web_secrets_route.py`, `test_web_content_providers.py`, `test_anthropic_compat_generator.py`, `test_openai_compat_generator.py`)
- Frontend: 4 real-browser e2e (`test_web_key_entry_e2e.py`, port 18582) — form appears for unavailable keyed provider, hidden for available, save POSTs correct `{provider,key}` + shows success, rejection shows error
- TDD: #1/#3 written test-first, red confirmed before fix
- Re-run to verify: `uv run pytest packages/studyloop/tests/test_web_key_entry_e2e.py -m e2e` and the 5 backend suites above

### What's OPTIONAL / outstanding (non-blocking — web flow fully covers the ask)
- **CLI parity (gap #4)**: `studyloop generate-cards` (`cli/_content.py:263`) has NO `--provider`/`--model`/`--backend` flags — it reads `settings.card_generator` from `config.yaml` only. A user wanting a non-default provider via CLI must edit the config. Low priority.
- **CLI missing-key prompt (gap #5)**: when a key is absent the CLI raises `CardGenerationError`; no interactive `click.prompt` to enter + store it. Low priority.
- Neither blocks the original feature (delivered via the web panel). Do these only if CLI users need provider control.

### To merge (when ready)
```
git checkout main && git merge --no-ff feat/provider-key-entry
```
It's a clean fast-forwardable history off current `main`; no conflicts expected.

---

## Branch 2 — `feat/struggle-extraction-pipeline` (BLOCKED on quality gate)

**Full detail lives in** `docs/handoffs/2026-05-31-struggle-extraction-P6-results-and-data-expansion.md` — read that for the complete picture. Summary here:

### State
P0–P6 built, tested, committed (11 commits). The pipeline, hill-climber, eval harness, and safety rails all work. The LLM struggle-extractor improved ~3.5× on unseen data (held-out F1 0.095 → 0.333) **but does not pass the gate** (held-out precision/recall 0.33/0.33 vs required 0.70/0.60; fp-on-negatives 0 holds).

### Root cause = data, not prompt
Train F1 0.667 vs held-out 0.333 = overfitting to a tiny 5-session training split. More prompt tuning overfits harder. **Next step: label ~15–20 more kiro_cli study sessions** (target ~25 total, ~18 train / ~7 held-out), then re-run P6. Method + commands in the dedicated doc.

### Key facts for resuming
- Bedrock Converse + forced tool-use (NOT LiteLLM/httpx — the original handoff was wrong). Model `us.anthropic.claude-sonnet-4-6`, region `us-east-1`, **profile `arraafat+prod-taylaand`** (the `bedrock-prod`/`bedrock-local` defaults are EXPIRED).
- `boto3` is behind the `[bedrock]` extra → eval/live runs use `uv run --with boto3`.
- Generated artifacts gitignored: `extractor_candidate.py`, `results.tsv`.
- P7 (production backfill of `study_progress`, the only live-DB write) is blocked until the gate passes.

---

## Shared environment facts (both branches)

- **Repo is local-only** — no remote, no `git push`, ever. Merges stay local.
- **CLI is click + LazyGroup** (not typer); tests use `click.testing.CliRunner`.
- **Reinstall after changes** that affect the installed tool: `uv tool install --reinstall './packages/studyloop[sessions]'` — a stale install serves old static assets / misses new CLI commands and looks like a product bug (recurring trap this session).
- **`uv run` prefix** for all pytest/tooling. New `.venv` per project.
- **Git index.lock races**: a background process intermittently grabs `.git/index.lock` in this repo. If a git command fails with "Unable to create index.lock", `rm -f .git/index.lock` and retry — the lock is stale (no real git process running).
- Working-tree note: switching to a `main`-based branch leaves `packages/studyloop/src/studyloop/extractors/` as an untracked dir (its files are tracked only on the struggle branch + gitignored artifacts). Harmless; do not `git add` it on `feat/provider-key-entry`.

## Suggested next-session options
1. **Merge `feat/provider-key-entry` to `main`** (feature is done) — fast, closes the original ask.
2. **CLI parity** on `feat/provider-key-entry` — add `--provider`/`--model` to `generate-cards` + an interactive missing-key prompt (gaps #4/#5).
3. **Expand the golden set** on `feat/struggle-extraction-pipeline` — the real unblock for the struggle pipeline (read the P6 doc first).

## Teaching notes saved this session (Obsidian, ~/Obsidian/Personal/Sessions/)
- `2026-05-31-mocks-test-logic-not-assumptions.md` — mocks test your logic, not your assumptions about a dependency (nova-lite passed mocks, crashed on real data).
- `2026-05-31-goodhart-and-the-held-out-gate.md` — optimised metrics stop being trustworthy; the held-out split is the only honest gate.
- `2026-05-31-fix-the-root-cause-not-the-symptom.md` — a degenerate optimiser output indicts the objective, not the thing optimised.
