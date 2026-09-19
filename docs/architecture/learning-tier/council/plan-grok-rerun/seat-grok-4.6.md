## VERDICT

VERDICT: ACCEPT-WITH-CORRECTIONS — item 1 is the right work if additive writers are auto-approved, SRS mutators stay gated, and `tutor-checkpoint` is replaced by a tested trigger table; item 2 is a directional eval on a not-yet-restored ruler and must not share a branch or carry an adopt-for-wiring clause.

## FINDINGS

| id | severity | claim | concrete check |
|---|---|---|---|
| B1 | BLOCKING | Auto-approving all of `W` writes SRS mutators into the live 924 MB DB. `record_study_progress` / `log_review_outcome` can invent card outcomes and corrupt scheduling. kiro today pre-approves only `log_topic` among writers; expanding that set is the data-loss step. | `mcp/tools.py:114` and `:648`: confirm no card-existence CHECK. `agents/kiro/study-mentor.json` `allowedTools` (readers + `log_topic` only). Split `W_auto` vs `W_srs` before S1-GREEN. |
| B2 | BLOCKING | S2-RULER does not specify connection mode. A default SQLite open on `~/.config/studyloop/sessions.db` (924 MB) or the 1.30 GB archive can take a write lock or checkpoint WAL. | `extractors/eval_runner.py` connect/open; require `file:<path>?mode=ro` or `immutable=1` on both DBs. Dry-run `lsof` must show no write fd on either file. |
| B3 | BLOCKING | `pre_filter(..., source in STUDY_SOURCES)` at `extractors/pipeline.py:35` is the same class of footgun that parked Bedrock. The three missing gold sessions are `claude_code`. A "13/13" restore that then filters them is a fake restore; live negatives stay 2/5 and the FP=0 gate stays broken. | Membership of `claude_code` in `STUDY_SOURCES`. Recompute resolved gold ids after filter: `agent-aa1015b3cd2de6078`, `agent-adb2db81040728397`, `agent-a86e019` must remain 13/13. Gold path must not use that pre_filter. |
| B4 | BLOCKING | Archive is pre-rebuild; live is schema 48. S2-RULER has no schema probe. Empty/misaligned transcripts can still "find" 13 ids and score garbage. | `PRAGMA user_version` on live and on `~/.config/studyloop/archive/sessions-archived-20260912.db`. Compare to `agent-session-tools/.../migrations.py` (teach-back CHECK is migration 10, `:500-515`). Fail loud on mismatch; do not coerce. |
| B5 | BLOCKING | `agents/grok/` does not exist. S1-RED "parity across six defs" cannot fail for a stated grant reason on grok; it can only invent a file. grok is `PREVIEW_HARNESSES`. | `packages/studyloop/src/studyloop/harnesses.py:28-49`; brief §3.2. Parity test must encode grok as skip/xfail until an adapter-owned definition exists. Do not create `agents/grok/` in this programme. |
| M1 | MAJOR | S1-SIM + grant files will be read as "the tier is fed." Brief §3.3: a scripted learner cannot test noticing. 0 writer calls in 143,973 messages is a persona/trigger failure, not a missing MCP symbol. | DoD text in the S1 PR. Replay fixture asserts rows from a recorded tool-call sequence (MCP plumbing), not "mentor decided to write." |
| M2 | MAJOR | Adopt-for-wiring on held_out (n=5) is an overclaim. Live negatives are 2/5; held-out negative count is UNVERIFIED and may be 1. C1 recall 1/9 is from 83 ledger rows, not these 13. | `eval_split.json` held_out ∩ {8 pos, 5 neg}; count held-out negatives after 13/13 restore. Recompute C1 on the same 13 or drop C1 as a bar. `results.tsv` is 6,968 bytes, untracked. |
| M3 | MAJOR | Item 2 scores frozen historical gold. It does not need item 1. One worktree lets Jev spend/privacy block agent-definition landing. | Two branches from `4f8e3e0f`. No shared worktree. |
| M4 | MAJOR | C2's bounded list is unspecified. Seeding it with the 23 gold slugs is oracle vocabulary; J-a/J-b then cannot isolate judgement from vocab. | Pre-register list construction from plan/backlog/`study_progress` only, never from `eval_golden.json`. Recompute train coverage of the 23 slugs against that list before any Jev call. |
| M5 | MAJOR | `agents/kiro/study-mentor/persona.md:32` still names `uv run tutor-checkpoint` (`agent_session_tools.tutor_checkpoint:main`, `packages/agent-session-tools/pyproject.toml:51`). A new protocol file beside that line leaves the only concrete command pointing at the wrong tool. | `rg -n tutor-checkpoint agents docs`. Same commit must delete/reconcile `:32` and every other hit. |
| M6 | MAJOR | Archive negatives are 196/187/150 messages. Jev `state`+question cap is 32k tokens. Chunking can split or duplicate a session-level label and invent FPs/FNs. | Token-count learner-turns-only for those three ids after the scrubber. If any chunk-set exceeds 32k, pre-register the chunk→session reduce rule before S2-TRAIN. |
| M7 | MAJOR | claude has zero `mcp__studyloop__*` in `settings.json` and zero tool names in `socratic-mentor.md`. Grants without persona triggers will not produce calls. | After S1-GREEN: `rg 'mcp__studyloop__|record_teachback|log_struggle' agents/claude/`. Both permissions and names must be present. |
| N1 | MINOR | `session_id` is optional on the CLI writer. An MCP mirror that trusts the model will orphan rows. | `history/teachback.py:27`; how `log_topic` at `mcp/tools.py:583-618` binds session. MCP path must default from server context. |
| N2 | MINOR | Jev is an API-key vendor. Standing rule forbids product-required keys. | No import of Jev from `content/generators/provider_profiles.py` or `mcp/tools.py`. Eval scripts only, pin `jev-1.13.0`. |

## ANSWERS

**Q1.** MCP `record_teachback` is the right call. CLI-only already failed: `agents/shared/teach-back-protocol.md:127-140` tells the agent to shell out, and zero writer calls exist in 143,973 messages. Shell-out also assumes a shell and a mid-lesson approval. Mirror `cli/_teachback.py:16-46` (five ints 1–4, `review_type` enum) and delegate to `history/teachback.py:27`. Keep the CLI for humans. Recommendation: add the MCP writer; do not teach harnesses to shell out.

**Q2.** Codex, pi, grok grant grammar is UNVERIFIED (`agents/codex/AGENTS.md`, `agents/pi/AGENTS.md`, no `agents/grok/`). Do not guess strings. kiro `allowedTools` omitting writers is a defect for additive writes (mechanism of the unfed pipe; data is already local) and an intended brake for SRS mutators (`mcp/tools.py:114`, `:648`). Recommendation: S1-RED fails per harness until the file+grammar is named from the tree; auto-approve `W_auto={log_topic,log_struggle,record_teachback,record_plan_learning}`; keep prompt-per-call on `record_study_progress`, `log_review_outcome`, `record_topic_progress` until those functions reject unknown `card_hash` / topic ids.

**Q3.** Prose-only will lose to `persona.md:32`. Ship a fenced YAML trigger table in `agents/shared/recording-protocol.md` plus one-line prose. CI: parse the YAML; assert the same bytes in every copy `scripts/install-agents.sh` projects; assert each persona names every `W_auto` tool; `agents/manifest.json` hashes match. Host in `tests/test_adapter_parity.py` and `tests/test_docs_harness_tier_contract.py`. Recommendation: machine-readable table; retire `tutor-checkpoint` in the same commit; regenerate `agents/manifest.json` and `.secrets.baseline` with a whole-repo `detect-secrets scan --baseline`.

**Q4.** Scripted ACC proves plumbing, not noticing (§3.3). Merge on: parity + `record_teachback` contract + projection + one replay fixture against a scratch DB (plan-agent shape, `scripts/plan_agent_harness.py`). kiro `STUDYLOOP_ACC=1` teach-back episode must insert one `teach_back_scores` row and one `session-topics.md` line under scratch HOME (`tests/acceptance/isolation.py`). Other harnesses skip-by-name. Owner-as-learner is a post-merge observation. Recommendation: reword DoD to "pipe open on kiro + grants proven in CI"; do not wait for six binaries.

**Q5.** live ∪ archive, read-only. Do not re-import: live is a filtered clean start; archive may still hold the 2026-09-09 bearer token; owner forbade deletions, not pollution. Guard: `mode=ro` on both; refuse unless 13/13 ids resolve; fingerprint each (`test_eval_receipt.py`); schema probe vs 48; do not run `pipeline.py:35` on gold. Recommendation: new `extractors/gold_source.py`; never `ATTACH` the archive to the live file.

**Q6.** J-c cannot emit `(topic, concept)` — component only, not a ruler arm. J-a is measurable only if a *non-gold* candidate list covers ≥50% of the 23 train slugs; that coverage is UNMEASURED and unlikely (23 distinct labels / 13 sessions). J-b is scorable but is a pipeline; it violates "measure Jev" if the receipt says Jev classified struggles. Pin the namer. Recommendation: coverage gate first; skip J-a if <50%; run J-b as a named pipeline plus J-c as appendix; do not sell J-b as Jev-only.

**Q7.** n=13 is directional. Held-out negatives may be one example. C1's 1/9 is the wrong denominator. `FP=0 ∧ recall>C1 ∧ Jaccard≥C2` as adopt-for-wiring will overclaim. Recommendation: drop the adopt/reject clause; report the runner's four metrics plus `eval.metrics` cluster-bootstrap CIs on train and one held-out pass; council reads the receipt before the owner.

**Q8.** Nothing in item 2 is a prerequisite for item 1. Nothing in item 1 is a prerequisite for scoring frozen gold. Feed-then-measure is a product narrative, not a data dependency. One branch serialises unrelated risk. Recommendation: `feat/learning-tier-fed` and `feat/jev-struggle-eval` from `main` at `4f8e3e0f`; two PRs; do not wait for S1-SIM to start S2-RULER.

## REVISED STAGING

Two worktrees, two branches off `4f8e3e0f`. Full-suite diff vs a clean control worktree each stage. Push only on owner say-so.

**Item 1 — `feat/learning-tier-fed`** (`~/code/personal/tools/studyloop-wt/tier`)

| Stage | Content | Finish line |
|---|---|---|
| S0 | Programme dir `docs/architecture/learning-tier/`; this arbitration | branch exists; brief + this verdict committed |
| S1-RED | Parity for `W_auto` on kiro/claude/opencode/codex/pi; grok skip/xfail; `record_teachback` contract (CLI-identical validator, CHECK 1–4, row lands); trigger-table projection test | N tests fail on `main` for those reasons; 0 unrelated reds vs control |
| S1-GREEN | MCP `record_teachback` binds `session_id` from server context; grants in each named grammar; `recording-protocol.md` YAML + prose projected; `persona.md:32` gone; `rg tutor-checkpoint` clean under `agents/` `docs/`; manifest + whole-repo `.secrets.baseline` | RED→green; goldens unchanged; ruff, format, pyright, bandit, pytest |
| S1-SIM | kiro ACC scripted vague teach-back → evidence bundle → CI replay fixture (MCP layer, scratch DB) | one `teach_back_scores` row + one `session-topics.md` line in scratch; replay green in CI; DoD says plumbing, not noticing |

**Item 2 — `feat/jev-struggle-eval`** (parallel; no code dep on item 1)

| Stage | Content | Finish line |
|---|---|---|
| S2-RULER | `extractors/gold_source.py`: live ∪ archive `mode=ro`, fingerprints, schema probe, no `STUDY_SOURCES` filter, 13/13 guard, scrubber hard-gate (`tests/test_scrubber.py`) | refuses on 12/13 and on schema mismatch; passes on 13/13; no write fd on either DB |
| S2-PREREG | `docs/architecture/learning-tier/receipts/preregistration-item2.md`: C0/C1-recomputed-or-dropped/C2 list recipe/J-arm rule; directional; no adopt clause; chunk reduce rule if 32k exceeded | receipt sha in the next commit message; **zero** Jev calls before this sha |
| S2-COV | C2/J-a candidate list from plan/backlog/`study_progress` only; train coverage of 23 slugs | number committed; J-a skipped if <50% |
| S2-TRAIN | C0 + honest C2 + allowed J arm on train; pin `jev-1.13.0`; scrub; learner turns only; spend ledger | receipt with numbers + usage |
| S2-HELDOUT | one pass; CIs; no re-run | receipt; council seat reviews before owner |

## UNVERIFIED

- Codex / pi / grok grant file and grammar; where the grok prompt lives given `packages/studyloop/src/studyloop/adapters/grok.py` and no `agents/grok/`.
- Exact Claude permission key strings (`mcp__studyloop__*` is a guess shape, not a cited grammar).
- Whether `scripts/install-agents.sh` auto-picks a new shared file or has an allow-list.
- `STUDY_SOURCES` membership of `claude_code`.
- Archive `user_version` vs live schema 48; transcript table shape after the 2026-09-12 rebuild.
- `eval_runner.py` current connect flags.
- Whether `record_study_progress` / `log_review_outcome` already reject unknown `card_hash`.
- How MCP tools bind `session_id` today.
- Gold-label coverage by any learner-data list; held-out negative count after 13/13 (2 train + 1 held-out ids are the missing negatives; the 2 live negatives' split is not in the brief).
- Token counts of the three archive sessions after learner-turns-only + scrub.
- Whether `docs/architecture/learning-tier/` allow-listing matches `plan-integration`.
- Whether `tutor-checkpoint` is still required by any non-mentor skill.
- Whether the 2026-09-09 bearer token is in one of the three archive negatives.

## ONE THING

Replace both false finish lines in the same arbitration commit: item 1 DoD is "pipe open" (`W_auto` granted, `persona.md:32` gone, YAML triggers projected, kiro scripted episode + CI replay land rows) — not "the mentor will write in the wild"; item 2 is a directional receipt on a 13/13 `mode=ro` ruler with no adopt-for-wiring clause and no Jev call before the pre-reg sha.
