# Arbitration — council review of "StudyLoop Modules — contract v1"

Date: 2026-10-04. Coordinator: Kiro (Claude lineage; also the proposal's author).
Seats: `gpt-5.6-sol` (OpenAI), `glm-5` (Zhipu), `deepseek-3.2` (DeepSeek), `qwen3-coder-next`
(Alibaba). Brief: `2026-10-04-review-brief.md`. Results: `2026-10-04-seat-*.md`.
Verdicts: 3× "adopt with changes" (GLM, DeepSeek, Qwen), 1× "rework" (GPT).

Every code claim relied on below was re-verified by the coordinator against the tree at
`75bab230..7ea6ec3e` before adoption. Claims that failed verification are listed in §5 and
carry no weight.

## 1. Where the seats agree — adopted

1. **W1 is the blocker, not a footnote (4/4).** Nothing in core delivers a verification result
   to the mentor process; `verify_practice_task` returns a result object and writes a
   `practice_attempts` row, and the only caller is the CLI
   (`packages/studyloop/src/studyloop/cli/_practice.py`). The proposal's "the mentor is told
   the result" is unbacked. → §5.6/§5.7 must specify the channel as a contract item and the
   DoD must prove it.
2. **The runner needs an execution model, not a working directory (4/4).** Verified against
   `learning/practice.py:282-290`: the existing seam runs the confirmed string with
   `shell=True`, inherits `os.environ` (no `env=`), captures all output and truncates only
   when persisting (`[-8000:]`). Converged fixes: `shell=False` with a single
   `scripts/<file>` argv plus literal arguments; a clean environment with scratch `HOME`,
   minimal `PATH` and only the `STUDYLOOP_*`/`KUBECONFIG` variables core sets; the consent
   bound to the content digest of the script *and* the argv, re-checked at spawn (R-15b today
   compares only the command text); streamed output caps with redaction before persistence or
   delivery; and a separate, fresh consent for every `setup` and `cleanup` execution.
3. **Cut W3 — view-only kubeconfig moves to v2 (3/4 explicit; Qwen's Q8 argues the same
   case while its Q3 says "reject").** GPT's framing is adopted verbatim in spirit: in v1 the
   core-created, per-attempt disposable cluster is the blast-radius boundary, learner-owned
   contexts are forbidden, and the injected kubeconfig contains exactly one context. RBAC
   `view` protects one phase and leaves admin setup/cleanup and host-shell execution
   untouched, so it does not buy what its cost suggests.
4. **A second module would NOT fit without a contract change (3/4: GPT, DeepSeek, Qwen).** An
   in-process DuckDB lab needs a core-owned `duckdb-database` attempt target (create, load
   declared fixtures, expose a path, destroy); running it as `workdir` + shell quietly turns
   "in-process" into an external-CLI dependency, and DuckDB is not a core dependency. GLM's
   "yes, `workdir` suffices" is rejected on that ground. Consequence: `duckdb` leaves the v1
   prerequisite enum (three ids: `docker`, `kind`, `kubectl`), and §10 Q6's recommended
   answer flips to "no — and that is precisely the stage-2 test".
5. **The estimate was low (4/4).** Seats: 70–85 (GPT), 55–70 (DeepSeek), 50–65 (GLM), 42–52
   (Qwen) agent-hours as written, against the coordinator's 45–60. Adopted: **55–70 as
   written**.
6. **"Three fields" is wrong (GPT, Qwen).** Four are marked ★ (`solution`, `scaffolding`,
   `mentorNotes`, `cleanupCommand`); DoD item 1 repeats the error. With the new `id` fields
   (below) it becomes six.

## 2. Where the seats agree against the coordinator — said plainly

- **§5.7 contradicts DoD item 3 (GPT; verified).** §5.7 promises a pass creates no learning
  record, yet item 3 routes the scaffold through the existing `practice verify` path, which
  records a `confident`/`struggling` observation and links it to learner history
  (`learning/practice.py:179-188`). The MVP needs a transient-only recording variant; the
  existing path cannot be "reused" as written.
- **The Web slice cannot start after the schema alone (GPT, DeepSeek; Qwen on ordering).**
  My ownership table was wrong. Browser-triggered execution depends on the hardened runner,
  an exact-consent protocol for HTTP (the existing origin check is consumed only by the
  WebSocket routes — `web/routes/session/_ws.py`, `web/routes/content_gen/_ws.py`), active-
  session binding, and the mentor channel. Adopted: **Labs discovery + drill start stay in the
  MVP; browser "Check progress" execution moves to v1.1**, and the runner is proven through
  the CLI first. Cost: the MVP's browser journey has no check step, so the one-button promise
  to the learner slips one release; stated in the proposal rather than hidden.
- **`STUDYLOOP_DRILL_ID` has no source (GPT; verified).** Neither deck nor task has an `id`;
  identity would be array position or prompt text. Adopted: stable lowercase-hyphen `id` on
  deck and task; drill identity is `(module id, module digest, deck id, task id)`.
- **No `--yes` equivalent on the web (GPT; verified `cli/_practice.py:77-87`).** The CLI's
  `--yes` pre-authorises before the command is displayed. Acceptable for scripts; the HTTP
  path must issue a one-use challenge after display, bound to digest + argv + phase +
  target + expiry.

## 3. Where the seats diverge — picked, with reasons and cost

- **W4, local-path-only `module add`.** GPT and Qwen accept (no network, no URL/ref parsing,
  no supply-chain semantics in v1); GLM and DeepSeek reject (sha pinning is the point of a
  lockfile; provenance must survive a reinstall). Both are right about different things:
  reproducibility is the content digest, provenance is where it came from. **Picked: a third
  option.** `module add <path>` only, but when the path is a git checkout core records the
  remote URL and `HEAD` sha in `modules.lock.json` as provenance metadata, read locally with
  no fetch. Cost: `add` cannot re-materialise a module by itself — the human clones. That is
  the stage-3 feature, not v1's.
- **Can Bruno start converting before the schema lands?** GLM says yes against the draft;
  DeepSeek says no, nothing validates until item 1. **Picked: both, by sequencing.** Item 1 is
  2–3 hours and ships first, within days, so the window in which "draft only" matters is
  short; Bruno drafts decks against the proposal text and validates the moment item 1 merges.
  Qwen's proposal to build `module check` before the schema is rejected: the checker is
  defined by the schema.
- **Mentor delivery mechanism.** GLM: session-scoped file the mentor polls; GPT: typed,
  size-bounded `practice_check` envelope pushed into the one claimed PTY/ACP session, with
  module text labelled untrusted and delivery failure reported. **Picked: GPT's shape** as the
  contract requirement (push, typed, bounded, failure visible), with the transport-level
  mechanism left to the design slice — the coordinator has still not read the transport code
  and will not specify what it has not verified.

## 4. New items adopted from single seats

- MC013 — every resolved deck/script path is a regular file inside the module snapshot; no
  symlinks, hardlinks, devices or path escape (GPT; GLM's variant folded in).
- MC014 — deck and task `id`s present, slug-valid, unique in scope (GPT).
- MC015 — each phase command is one `scripts/...` executable plus literal arguments; no
  shell operators, substitutions or interpreters (GPT; the static half of `shell=False`).
- MC016 — no capability declared that no deck uses (GLM).
- Every phase has its own timeout; `timeoutSeconds` applies per phase, and timeout is an
  error, never a fail (DeepSeek, Qwen).
- Exit-code wording: "1 = check failed (task not complete)" replaces "not yet", which one
  seat read as a running state (Qwen).
- §7 gains the sentence GLM asked for: in v1 the learner clicks explicitly; there is no
  automatic check after each command.
- `module add` writes the lockfile only after `module check` passes (DeepSeek).
- Clarify that a drill runs *inside* the one claimed session (ADR-0009); the runner is a
  subprocess of the server, not a second session (Qwen's question, answered).

## 5. Claims verified false — discounted, with the seat's other unverified claims weighted down

- DeepSeek: "`doctor/` contains only `__init__.py` and `checks.py`". False — eleven check
  modules exist. DeepSeek's "C3 conflicts with the v2 grant" is also rejected: C3 is scoped to
  v1 in the brief. Its "redesigning a Secrets drill violates the Socratic rule" confuses a
  credential boundary with the answer-giving rule; moot once W3 moves to v2.
- Qwen: "`agents/shared/` does not exist, `agents/` is empty". False — fourteen entries,
  including `personas/`. Qwen's cited line numbers in `practice.py` do not match the file;
  its behavioural claims (env inheritance, `shell=True`) are nonetheless true and were
  adopted on the coordinator's own verification, not Qwen's citations.
- GLM's `schemas.py:52-53` citation is the wrong location for the `extra: forbid` it
  describes; the claim is true at the practice models. GLM asked for an example that
  validates today; rejected — the example shows the target format and already carries the
  "fails today" note. GPT and GLM were the only seats whose cited lines matched the tree.

## 6. What the brief itself got wrong

- It asked about "three" fields and so inherited the proposal's miscount.
- It did not list the §5.7/DoD-3 contradiction as a weak point; GPT found it from the code.
- It stated I5 (mentor channel unverified) and then let the DoD omit any proof of it.

## 7. Revised estimate and verdict

- As written (council-corrected): **55–70 agent-hours.**
- Revised MVP — W3 and W4 cut, runner hardening added, transient-only recording path added,
  Labs listing and start in, browser execution out: **40–50 agent-hours.** v1.1 (HTTP consent
  endpoint, mentor envelope, full browser journey): **a further 15–20.**
- Verdict: **adopt the direction; rework §5.3 (identity), §5.5 (execution model, consent),
  §5.7 (evidence path), §9 (sequencing) and §10 (Q2, Q4, Q6, Q8 recommended answers) before
  sharing.** The contributors should read the amended proposal, not this one.
