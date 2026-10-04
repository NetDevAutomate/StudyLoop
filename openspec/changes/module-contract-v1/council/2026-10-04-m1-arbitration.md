# Arbitration — council M1, the drill runner (lane R), 2026-10-04

**Coordinator:** Kiro (default). **Brief:** `2026-10-04-m1-brief.md`. **Subject:** `feat/module-runner`
at `713194dc`. **Seats:** gpt-5.6-sol (re-dispatched after refusing the brief's "attacker" wording;
731 w, 10 cites, 10 findings, *do not merge*) · glm-5 (478 w, 6 cites, 5 findings, *merge after
fixes*) · qwen3-coder-next (746 w, 9 cites, 2 findings, *merge after fixes*) · deepseek-3.2 (1,447
w, 0 cites, format ignored, "approved with gaps"). Every adopted finding was re-verified by the
coordinator in the worktree before a ruling was written.

## 1. Seat reliability

| Seat | Held | Did not | Weight |
| --- | --- | --- | --- |
| gpt-5.6-sol | 10/10 located in code and consistent with it: NUL/oversize argv spawns after consent (`runner.py:113-137`); digest-redeem→exec window (`:413-425`); scratch HOME is hygiene, not containment (`:203-231`); PATH ruling; `setsid` grandchild survives `killpg` (`:234-251`); truncate-before-redact (`:297-309,452-458`); hop sends rendered `message` against M0's typed-fields ruling (`hop.py:105-127`); state file accepted without owner/mode check (`:130-149`); digest format drift between C's `sha256:<hex>` and hop's documented raw hex (`_drill.py:98-104`); sidecar one `..` above cwd is same-UID writable (`attempt.py:324-352`) | — | full |
| glm-5 | truncate-before-redact (independent of GPT); state-file trust; `(attempt_id, phase)` has no UNIQUE | labelled a NUL byte an EXPLOIT — CPython raises `ValueError: embedded null byte` before exec, so it is a clean-error weakness (GPT's finding 1 is the correct shape) | partial |
| qwen3-coder-next | read the right tree this time; confirmed symlink/hard-link rejection at `runner.py:573-574` and the 0600 token file; `setsid` grandchild (independent of GPT) | PATH item was handed to it by the brief; wrote its file into the lane worktree instead of the named path | confirmation |
| deepseek-3.2 | `${PATH}` passes `validate_argv` (true; literal under `shell=False`) | claimed `$((1+2))` and `<<<hello` pass — both are **rejected** (coordinator ran `validate_argv`); quoted a `practice_check_events` DDL with `session_id`, `message`, `stdout_tail` columns that **does not exist** in `attempt.py`; recommended adding `/sbin:/usr/sbin` to the child's PATH — the opposite of least privilege; 0 cites, over budget | near zero |

Fifth council today with the same shape. Qwen is kept for M2 on the strength of this seat (right
tree, correct confirmations); DeepSeek's fabricated DDL is its second fabrication today (planning
council: invented commit history) and it is **dropped from M2** unless the owner says otherwise.

## 2. Rulings, by question

**Q1 shell/argv.** The boundary holds for everything the brief listed except two: a NUL byte or a
multi-megabyte argument passes the 64-item check and fails *after* consent with an uncaught
exception. **Fix (R):** reject `\x00`, cap total encoded argv bytes, validate before the consent
prompt, and turn every spawn failure into `PhaseResult(ERROR)`. Add `${` to `SHELL_TOKENS` (cheap
defence in depth; DeepSeek's one true item).

**Q2 environment and PATH.** Nothing from `os.environ` reaches the child — verified. But scratch
HOME/cwd is **hygiene, not containment**: the script runs with the learner's privileges and the
proposal never promised otherwise (`proposal.md:224` — "a working directory is not a sandbox; the
boundary is the whole execution model"). **Ruling:** v1 is consent-gated execution with hygiene.
The runner's docstring, ADR-0012 and the per-phase consent prompt SHALL say so in plain words
("this script runs with your privileges"); OS sandboxing (`sandbox-exec` / `bwrap`) is a tracked
follow-up change, not a v1 fix. **PATH ruling (GPT's shape, adopted):** core resolves each
prerequisite the module declares to a canonical executable on the *learner's* PATH at consent time,
builds a per-attempt `bin/` holding symlinks to exactly those tools, and the child's PATH is
`<attempt>/bin:/usr/bin:/bin`. "Modules declare, core executes" — kubectl under
`/opt/homebrew/bin` resolves without exposing the rest of Homebrew. R implements the resolver with
an injectable tool list now; the manifest wiring lands when C's `manifest.py` is on main.

**Q3 consent.** Holds: argv + digest + phase + target, single use, 600 s, no `--yes`. The
redeem→exec window (GPT 2) is narrowed two ways: **C** publishes snapshot *directories* 0o555 as
well as files (`module remove` chmods before deleting), and **R** re-verifies the script digest
immediately before `Popen`. The residual same-UID race is inside the v1 threat model above.

**Q4 caps, timeout, kill.** Caps and `killpg` verified. A grandchild that calls `setsid()` survives
— true, and portable Python cannot fix it. **Ruling:** documented residual (ADR + docstring), part
of the sandbox follow-up.

**Q5 redaction and recording.** The byte cap truncates during streaming and redaction runs on the
truncated bytes, so a secret cut at the boundary half-survives (GPT 6, GLM 1 — verified at
`runner.py:300,457`). **Fix (R):** stream to `limit + 8 KiB`, redact the whole captured buffer, then
cut to `limit`; `cap_hit` semantics unchanged. The DDL holds no output text — verified; DeepSeek's
contrary DDL is fabricated. GLM's `UNIQUE(attempt_id, phase)`: **not adopted** — replay dedup is the
server route's contract (M0 Q2, lane W); the runner records what ran.

**Q6 the hop.** Two real ones. The body carries `message` (rendered text) although M0 ruled "server
renders from typed fields" and T's envelope is `extra: forbid` with no `message` field — the hop
would be **rejected at integration**. **Fix (R):** send exactly T's envelope fields, canonical
`module_digest` = `sha256:<64 hex>` (C's `LockEntry.digest` already is; T's validator accepts it;
R's docstring and tests said raw hex). The state file is accepted without checks. **Fix (R):**
require regular file, owner == current uid, mode & 0o077 == 0; otherwise `no_active_session` with
the reason. The token being readable by a same-UID module is inside the v1 threat model.

**Q7 honesty.** "Never inherited environment" is true of `env=` and overstated as isolation; "whole
process group" is true and not the whole tree. Both sentences are rewritten under the Q2/Q4
rulings. The sidecar JSON (GPT 10) is the learner's own evidence, not a control: **Fix (R):** write
it after the child exits, `O_EXCL`, no-follow, parent 0o700.

## 3. Verdict carried

GPT's *do not merge* rests on findings 1, 6, 7 (demonstrated) and 3 (design). 1, 6, 7 are fixed
before merge; 3 is ruled as the v1 threat model and must be *written down* before merge. So:
**merge after fixes** — the fix list above goes to lane R as a red-first follow-up; the two C-side
items (snapshot dirs 0o555, `remove` chmods first) are queued on lane C's running follow-up.

## 4. Catch-rate

Raised 21 (gpt 10, glm 5, qwen 2, deepseek 4) · verified 15 · acted 11 (R fixes 8, C fixes 1,
docs/ADR 2) · ruled-not-fixed 4 (containment, setsid, same-UID token/race — v1 threat model) ·
discounted 6 (deepseek 3 false, glm NUL-as-exploit relabelled, glm UNIQUE not adopted, qwen PATH
handed by brief). Coordinator's call (4–8 findings, one ruling, `merge after fixes`) was close on
shape and low on count; it did not foresee the `message`-field contract break or the digest format
drift, both of which would have failed at W's route.
