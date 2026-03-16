# Handoff: Pipeline Restructure — Event-Driven Stages for notebooklm-repo-artefacts

## Session Metadata
- Created: 2026-03-15 01:28:44
- Project: /Users/user/code/personal/tools/Socratic-Study-Mentor
- **Target project**: /Users/user/code/personal/tools/notebooklm_repo_artefacts
- Branch: main (both repos)
- Session duration: ~3 hours

### Recent Commits (for context)

**notebooklm-repo-artefacts** (target repo — 6 commits this session):
  - 2f86190 refactor: replace _list_raw + RawArtefact with public artifacts.list() API
  - 57e4db9 refactor: use upstream notebooklm-py enums instead of hand-rolled copies
  - 1476546 fix: correct swapped VIDEO/SLIDES type codes in ArtefactType enum
  - 2483c6b fix: force artefact regeneration when source is replaced
  - 6926cca fix: wait for source ingestion before generating artefacts
  - 02d4ed3 fix: prevent store slug from resolving to real filesystem paths

**Socratic-Study-Mentor** (source repo):
  - c27d7ac style: format studyctl package with ruff
  - 36c5cd4 docs: update artefact links
  - 0f72c57 fix: rewrite Kiro exporter for v2 table and nested message format

## Handoff Chain

- **Continues from**: None (fresh start)
- **Supersedes**: None

## Current State Summary

We spent a session fixing critical pipeline bugs in `notebooklm-repo-artefacts` and then designed a full pipeline restructure. The current `pipeline()` in `cli.py` is a ~250-line monolithic function that caused 4 categories of bugs in one session: repo deletion (bad `--store` path), artefact deletion (swapped type codes), source ingestion races, and stale artefact serving. All bugs have been fixed individually, but the monolithic design remains fragile. A brainstorm document captures the agreed design for an event-driven pipeline with discrete stages, pre/post validation gates, JSON state persistence, and idempotent behaviour. The next session should implement this design, test it thoroughly, then run a full monitored end-to-end pipeline.

## Codebase Understanding

### Architecture Overview

`notebooklm-repo-artefacts` is a CLI tool (`repo-artefacts`) that:
1. Collects repo content → renders to PDF
2. Uploads PDF to Google NotebookLM as a source
3. Generates 4 artefact types (audio, video, slides, infographic)
4. Downloads artefacts locally
5. Publishes to a GitHub Pages artefact store
6. Updates source repo README with links
7. Verifies deployment

The upstream `notebooklm-py` (v0.3.4) provides the NotebookLM API client. Our code wraps it with auth retry, orchestration, and the store/publish/pages layer.

### Critical Files

| File | Purpose | Relevance |
|------|---------|-----------|
| `src/repo_artefacts/cli.py` | CLI commands including monolithic `pipeline()` | **Rewrite target** — replace pipeline() with new stage-based runner |
| `src/repo_artefacts/notebooklm.py` | NotebookLM API wrapper (upload, generate, download, poll) | **Refactored this session** — now uses public upstream API. Keep as-is, stages call into this. |
| `src/repo_artefacts/store.py` | Artefact store operations (clone, publish, manifest) | **Fixed this session** — slug validation + safe_rmtree added |
| `src/repo_artefacts/collector.py` | Repo content collection + PDF rendering | Untouched, works fine |
| `src/repo_artefacts/publish.py` | Git commit/push, pages verification | Untouched |
| `src/repo_artefacts/config.py` | Config loading (~/.config/repo-artefacts/config.toml) | Untouched |
| `docs/brainstorms/2026-03-15-pipeline-restructure-brainstorm.md` | **Design document** — read this first |
| `UPSTREAM_DEVIATION_REPORT.md` | Audit of deviations from notebooklm-py | Reference for remaining items |
| `tests/test_notebooklm.py` | 76 tests, all passing | Updated this session for public API |
| `tests/test_store.py` | 10 tests for store safety | Added this session |

### Key Patterns Discovered

- **Upstream `notebooklm-py` public API**: `client.artifacts.list()` returns `Artifact` objects with `.kind` (ArtifactType string enum like `"video"`, `"slide_deck"`), `.is_completed`, `.is_failed`, `.is_processing`, `.is_pending`. Use `.kind` not integer type codes.
- **`Artifact` constructor**: `Artifact(id=..., title=..., _artifact_type=<int>, status=<int>)` — tests use this to build fakes
- **`client.sources.add_file(..., wait=True, wait_timeout=180.0)`** — blocks until source ingestion complete
- **`client.artifacts.wait_for_completion(notebook_id, artifact_id)`** — upstream polling with exponential backoff (NOT yet used by our code — the brainstorm recommends adopting it)
- **Auth retry**: `_with_reauth()` wrapper handles AuthError, RateLimitError, RPCError with escalating backoff. Keep this pattern.
- **Store slug must be `org/repo` format** — `_validate_store_slug()` rejects absolute paths, tilde paths, `..`
- **Pre-commit hooks**: ruff lint + format, pyright, pytest, detect-secrets, check-links. All must pass.
- **`NAME_TO_KIND`** maps our config keys → `ArtifactType` string enum. `KIND_TO_NAME` is the reverse.
- **`ARTEFACT_CONFIG`** has 4 keys: audio, video, slides, infographic. Each has `method` (generate method name) and `instructions`.
- **`DOWNLOAD_MAP`** maps each type to list/download method names and output filenames.

## Work Completed

### Tasks Finished

- [x] Fix Kiro exporter (socratic-study-mentor repo — v2 table + nested message format)
- [x] Fix store slug validation — prevents shutil.rmtree on real repos
- [x] Fix source ingestion race — wait=True before generating
- [x] Fix staleness check — force regen when source replaced (source_replaced flag)
- [x] Fix swapped VIDEO/SLIDES type codes in ArtefactType enum
- [x] Refactor to upstream notebooklm-py enums (ArtifactTypeCode)
- [x] Replace all _list_raw() with public client.artifacts.list() API
- [x] Delete RawArtefact class and _parse_raw_artefacts
- [x] Switch from int ArtifactTypeCode to string ArtifactType
- [x] Run upstream deviation audit (pattern-recognition-specialist agent)
- [x] Brainstorm pipeline restructure design
- [x] Format studyctl package for CI
- [x] Generate + publish all 4 artefacts for Socratic-Study-Mentor
- [x] Verify all artefact URLs live on store

### Decisions Made

| Decision | Options Considered | Rationale |
|----------|-------------------|-----------|
| Event-driven pipeline | State machine, chain-of-responsibility, event-driven | Event-driven maps naturally to async NotebookLM operations (upload→ingest→generate) with polling |
| Python-native stages | Taskfile, Makefile, python-invoke, custom DAG | Keeps everything in one codebase, testable with pytest |
| JSON state file | JSON file, SQLite pipeline.db, extend sessions.db | Pipeline state is ephemeral, git+manifest provides audit trail. DB would couple unrelated concerns |
| Per-stage timeouts | Per-stage, global only | Generation takes 15+ min, other stages are fast. Need independent control |
| Sequential generation with 30s gap | Parallel, sequential | Avoid NotebookLM API rate limits |
| SHA256 content hashing | Hash, source_replaced flag only | Most precise staleness check — skip upload+generate if content unchanged |
| Use upstream public API only | Keep _list_raw, use public list() | Private API broke us (type code mismatch). Public API returns parsed Artifact objects with string enums |

## Pending Work

### Immediate Next Steps

1. **Read the brainstorm document**: `docs/brainstorms/2026-03-15-pipeline-restructure-brainstorm.md` in the notebooklm-repo-artefacts repo — contains full design with stage breakdown, event flow, and code sketches
2. **Implement the pipeline framework**: Create `src/repo_artefacts/pipeline.py` with:
   - `StageResult` dataclass (pass/fail/skip/retry)
   - `Stage` protocol (pre_check, execute, post_check, remediate)
   - `PipelineContext` (repo_path, store_slug, notebook_id, state, config)
   - `PipelineState` (JSON persistence after each stage)
   - `Pipeline` runner (event emission, stage orchestration)
3. **Implement 9 stages**: collect, upload, ingest, generate (sequential with 30s gap), download, publish, verify, readme-update, cleanup
4. **Write comprehensive tests**: Unit tests for each stage's pre/post checks, integration test for the full pipeline with mocked NotebookLM client
5. **Wire into CLI**: Replace monolithic `pipeline()` in cli.py with new Pipeline runner
6. **Run full E2E**: Against existing notebook `Socratic-Study-Mentor` (12f41d99-0d48-4ead-a550-acb71d5af77b) which still exists with completed artefacts — tests idempotency
7. **Monitor E2E closely**: Dedicated agent watching pipeline state, artefact status, notebook status. On ANY failure: tear down completely (delete artefacts, state, notebook if created), fix the issue, restart from scratch

### Blockers/Open Questions

- [ ] Upstream `wait_for_completion()` — should we use it for generation polling instead of our custom 30s loop? Check if it handles the case where status=COMPLETED but media URL not yet populated.
- [ ] The `publish` command currently requires `-n` notebook_id even with `--skip-generate`. The new pipeline should handle this internally.

### Deferred Items

- Table formatting issue in upstream `notebooklm` CLI (emoji width causing column misalignment) — upstream package issue, not ours
- `session-export` progress bar showing cumulative stats with wrong label — cosmetic, tracked in TODO.md

## Context for Resuming Agent

### Important Context

1. **The existing notebook must NOT be deleted before testing** — `Socratic-Study-Mentor` (ID: `12f41d99-0d48-4ead-a550-acb71d5af77b`) has 3 completed artefacts (audio, video, infographic) and completed slides. The new pipeline MUST handle this gracefully (detect existing, skip completed, only generate missing).

2. **The E2E test protocol**: If the pipeline hits ANY issue during E2E, the entire run must be torn down — delete pipeline state, local artefact files, and the notebook if it was newly created (NOT the existing one). Fix the code, then restart from scratch. A dedicated monitoring agent should watch `notebooklm artifact list` output and pipeline state JSON between stages.

3. **notebooklm-py is v0.3.4** — installed via mise's Python 3.14.3 at `/Users/user/.local/share/mise/installs/python/3.14.3/`. The repo-artefacts project uses Python 3.12.6 via uv.

4. **Store config**: `~/.config/repo-artefacts/config.toml` has `default_store = "NetDevAutomate/artefact-store"`. Store cache is at `~/.cache/repo-artefacts/stores/`.

5. **Git remotes**: Socratic-Study-Mentor uses SSH (`git@github.com:NetDevAutomate/Socratic-Study-Mentor.git`). The pipeline's publish step previously failed with HTTPS — we switched to SSH this session.

6. **The pipeline's `_delete_existing_by_type` still deletes ALL artefacts of a type before regenerating (line 474 in the current code)**. The new pipeline MUST NOT do this — it should only delete failed artefacts, never completed ones, unless `--force-regen` is explicitly passed.

### Assumptions Made

- NotebookLM API rate limits are ~20-25 infographics/slides per day (Pro tier)
- Sequential generation with 30s gap is sufficient to avoid rate limiting
- The upstream `Artifact.kind` property is stable and won't change between notebooklm-py versions
- JSON state file in artefacts dir is git-ignorable (add to .gitignore)

### Potential Gotchas

- **`Path(base) / "/absolute"` silently discards base** — already fixed in store.py but watch for this pattern anywhere paths are joined
- **Ruff format hook reformats on commit** — always re-stage after failed commit
- **pyright runs on pre-commit** — type annotations must be correct
- **`uv sync --all-packages`** needed after adding deps (not just `uv sync`)
- **NotebookLM generation can take 15+ minutes** — don't set timeouts below 900s for generation stages
- **The `generate` CLI command's `_delete_existing_by_type` with `failed_only=False` is destructive** — it deletes completed artefacts. The new pipeline must change this default.

## Environment State

### Tools/Services Used

- `uv` for Python package management (workspace with pyproject.toml)
- `ruff` for linting/formatting
- `pyright` for type checking
- `pytest` with `pytest-asyncio` for testing
- `notebooklm-py` v0.3.4 upstream library
- `rich` for CLI output
- `typer` for CLI framework
- NotebookLM API (Google) — auth tokens stored locally

### Active Processes

- None running. All background tasks completed.

### Environment Variables

- `GITHUB_TOKEN` — loaded from `tokens.age` by the publish step (encrypted)
- `NOTEBOOK_ID` — can be set as env var instead of `-n` flag

## Related Resources

- **Brainstorm doc**: `/Users/user/code/personal/tools/notebooklm_repo_artefacts/docs/brainstorms/2026-03-15-pipeline-restructure-brainstorm.md`
- **Upstream deviation report**: `/Users/user/code/personal/tools/notebooklm_repo_artefacts/UPSTREAM_DEVIATION_REPORT.md`
- **Current pipeline code**: `/Users/user/code/personal/tools/notebooklm_repo_artefacts/src/repo_artefacts/cli.py` (lines 369-620)
- **Current notebooklm wrapper**: `/Users/user/code/personal/tools/notebooklm_repo_artefacts/src/repo_artefacts/notebooklm.py`
- **notebooklm-py docs**: https://github.com/teng-lin/notebooklm-py/blob/main/docs/python-api.md
- **Memory file**: `/Users/user/.claude/projects/-Users-user-code-personal-tools-Socratic-Study-Mentor/memory/MEMORY.md`

---

**Security Reminder**: Before finalizing, run `validate_handoff.py` to check for accidental secret exposure.
