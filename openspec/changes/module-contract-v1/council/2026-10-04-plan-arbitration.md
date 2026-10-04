# Arbitration — planning council for "StudyLoop Modules — contract v1"

Date: 2026-10-04. Coordinator: Kiro (Claude lineage). Brief: `2026-10-04-plan-brief.md`.
Seats: `gpt-5.6-sol` (1,626 words, "re-sequence first", 18 days), `deepseek-3.2` (2,092,
"build as proposed", 10 days), `qwen3-coder-next` (3,357, "build as proposed", 10 days),
`glm-5` (1,437, "build as proposed", 10 days). Every code fact relied on below was re-verified
by the coordinator against the tree at `c8cf7b59`.

## 1. Reliability of the seats, established first

- **GPT-5.6**: every cited line checked out (`session/transport.py:145` `send_input`,
  `transports/pty.py:351-360` raw write, `transports/acp.py:267-290` fire-and-forget prompt
  turn, `session/active.py:50-54` transport handle, `docs/contributing.md:67` e2e machine
  lock, `Justfile:121-135` `testacc`/`testuat`). It also found a brief error (below). Weighted
  highest.
- **DeepSeek**: structurally sound plan, but one cited fact is false — there is no
  `"modules": []` key at `web/routes/session/_options.py:142` (the lines are config-record
  code; a grep for the key finds nothing) — and its Q9 "F10 is wrong" misreads F10, which is
  about the agent harness, not a StudyLoop command. Its proposal to copy `CHANGELOG.md` into
  per-lane `CHANGELOG.lane.md` files and merge back is rejected as unconventional churn.
- **Qwen**: nearly double the word budget; schedules seven concurrent agents against a cap of
  four; puts Bruno's kdrill conversion inside the core repo as a lane; and its tablet journey
  includes "tap Check progress (v1.1 stub)", which contradicts the MVP scope it elsewhere
  defends. Its test-plan table and R4 strategy are usable.
- **GLM**: **off-brief.** Its transcript says "based on the summary and what I've verified";
  it answered a different question set (Q2 "Sequence", Q4 "Critical-path items", Q8
  "Constraint adherence", Q9 "Cut-scope triggers"), invented features not in the proposal
  (`AGENT_HINT.md` injection, `/practice` endpoints, an evidence-prompt checklist) and
  treated the existing `practice verify` observation recording as a deliverable. Discounted
  entirely except for its verified transport citations, which GPT also made.

So the arbitration is effectively between GPT-5.6, DeepSeek and the usable parts of Qwen.

## 2. Where they agree — adopted

1. **Schema first, alone, fast** (3/3): DoD item 1 is its own lane and its own merge.
2. **Tests live with their lane; no separate test lane** (GPT, DeepSeek; Qwen's "test
   author" role is the exception and is rejected — it recreates the coupling GPT names).
3. **R4 is defeated by red-first evidence**: 16 single-fault fixtures that each fail on
   exactly one `MCnnn`, a repaired twin that passes, and the "no observation written" test
   shown failing against today's `practice verify` before the transient path exists (3/3).
4. **Representative user testing reuses the acceptance and UAT tiers** (`just testacc`,
   `just testuat`; `packages/studyloop/tests/acceptance/`, `.../acceptance/uat/`), with the
   existing `tests/e2e/_env.py` harness and its failure artifacts (3/3).
5. **The runner gets an adversarial council review before merge**; the schema does not need
   one (GPT, DeepSeek; Qwen's "all four seats at every milestone" is rejected as review
   inflation).
6. **A design-first transport spike precedes any mentor-delivery implementation** (3/3).
7. **Re-key the lane-ownership guard** rather than discard it (GPT, DeepSeek).

## 3. Where they diverge — picked, with reasons and cost

- **Lane shape: five (GPT) vs four (DeepSeek) vs seven (Qwen).** Picked **GPT's five**: S
  schema + guard, C conformance + lifecycle (+ doctor probes, which DeepSeek placed better
  than GPT did), R secure runner + `studyloop drill`, T mentor delivery, W Labs + final
  assembly. DeepSeek's four folds `module check` into the schema lane, which breaks "item 1
  ships alone"; Qwen's seven adds a docs lane that would edit `docs/contributor-modules.md`
  while another session is editing it. Cost of five: one more merge than DeepSeek's shape.
- **Docs and `CHANGELOG.md` ownership.** Picked GPT's **serialisation**: S alone writes the
  contract page, PR template, `mkdocs.yml` entry and first changelog entry, in a commit that
  waits for the other session's docs work to land; W alone does the final reconciliation.
  Nobody touches `docs/contributing.md` or `CONTRIBUTING.md`. A "docs lease" (one writer
  at a time) replaces DeepSeek's copy-and-merge-back.
- **Critical path: 18 days (GPT) vs 10 (three seats).** Picked **GPT's structure and roughly
  its number**. The 10-day plans either omit owner review time or assume the Web lane starts
  after the schema; GPT's dependency argument is correct and verified — W needs C, R and T,
  and ACP's `send_input` starts a prompt turn, so delivery serialisation must be decided
  before any UI assumes it. The binding constraint is the owner's two review-hours a day, not
  agent compute. Stated as **15–18 calendar days**, compressible to about 12 if the owner
  reviews four hours a day on weekends.
- **Effort: 46 h (DeepSeek) vs 64+6 h (GPT) vs 70 h (Qwen incl. kdrill).** Picked **60–70
  agent-hours for core**, excluding Bruno's conversion. The proposal's 40–50 was for
  implementation without adversarial tests or representative UAT; this plan includes both.
- **What to cut for a week:** GPT and DeepSeek say defer the Web Labs slice (ship a "CLI
  contract preview"); Qwen says cut the kdrill live proof. Picked **defer Labs, never the
  kdrill proof** — a standard nobody has run against a real module is not a standard.
- **Council milestones: 3 (GPT) vs 4 (DeepSeek, Qwen) vs 2 (GLM).** Picked **GPT's three**:
  M0 transport decision after the spike; M1 runner security boundary before R merges; M2
  release proof over the seven-item DoD and UAT artifacts. DeepSeek's "schema design review"
  reviews a settled decision and is exactly the mechanical use the skill forbids.

## 4. Where the seats corrected the coordinator (brief errors)

- **C3 was wrong**: the pyright hook in `.pre-commit-config.yaml` carries no `pre-push`
  stage (GPT; verified — the neighbouring trufflehog hook says `stages: [pre-commit]`, pyright
  has no stage override). `just preflight` is the authoritative typecheck gate; pre-commit's
  pyright runs at commit time, which is stricter, not looser.
- **F9 was too pessimistic**: a live-session transport handle exists
  (`session/active.py:50-54`, `ActiveSession.transport`) with a generic
  `send_input(bytes)` (`session/transport.py:145`). What is genuinely unknown is narrower:
  PTY framing (how injected text is distinguished from learner typing), ACP turn
  serialisation (`send_input` fires a prompt turn as a task — `transports/acp.py:267-290`),
  size bounds and failure surfacing. The spike is a day, not a week.
- **F5 counts** were approximate; GPT's read-only count is 4,669 test functions in 354
  files. Immaterial to the plan.
- **F3 was right** and the coordinator's own earlier recipe listing had missed `testacc` /
  `testuat` because they take parameters (`Justfile:121,134`).

## 5. Plan parameters carried into `design.md` and `tasks.md`

| Parameter | Value |
| --- | --- |
| Lanes | S, C, R, T, W (five); kdrill is an external handoff with an acceptance test owned by W |
| Branches / worktrees | `feat/module-<lane>` ; `../studyloop-wt-module-<lane>` ; bootstrap `env -u VIRTUAL_ENV just sync-dev` |
| Gate per commit | pre-commit (all hooks) + `env -u VIRTUAL_ENV just preflight`; `just e2e` serialised (machine lock) |
| Merge DAG | S → {C, R, T-spike}; T-spike → M0 → T; {C, R, T} → W; W + kdrill proof → M2 |
| Waves (cap 4 agents) | Wave 0: S impl, C red-tests, R adversarial red-tests, T spike. Wave 1: C, R, T impl + W tests-only. Wave 2: W impl. Then UAT, kdrill, M2 |
| Councils | M0 transport decision · M1 runner security · M2 release proof |
| Effort / path | 60–70 core agent-hours; 15–18 calendar days at 2 owner-hours/day |
| One-week cut | Defer W (Labs) to v1.1; never the kdrill proof |
