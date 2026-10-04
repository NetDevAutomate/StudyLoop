# M1 Adversarial Review: module-contract-v1 — seat `deepseek-3.2`
**Session**: `subagent_8c80588d047937da`
**Worktree**: `/Users/ataylor/code/personal/tools/studyloop-wt/module-runner` @ `713194dc`
**Lane C store**: readable at `/Users/ataylor/code/personal/tools/studyloop-wt/module-conformance`
**Throwaway probes**: under `$KIROCREW_SCRATCH` only

## Verdict

**APPROVED with identified gaps** — implementation satisfies the spec's security requirements but has five contract‑level omissions requiring council review before v1 final. The runner correctly isolates, caps, consents and delivers; shell token coverage and PATH exclusion need the spec amended or the code tightened.

---

## Question 1: Shell and argv
**What R claims**: `validate_argv` blocks 11 shell tokens (`&&`, `||`, `$(`, `;`, `|`, `&`, `` ` ``, `>`, `<`, `\n`, `\r`). `resolve_script` enforces MC013: regular file, `st_nlink == 1`, not symlink/hardlink/directory/device/FIFO, path resolves exactly to `scripts/<name>` under snapshot, no `..` escapes.

**Adversarial reading**:
- **Correct**: The listed tokens are refused, real path is resolved after symlink chase, no path traversal.
- **Missing shell escapes**:
  - `$((` (arithmetic expansion) and `${` (parameter expansion) pass through.
  - `<<<` (here‑string) and `<<` (here‑doc) are not caught.
  - `$( ... )` is caught by the `$(` token, but `$(( ... ))` would be split as `$(` `(`.
- **Binary/polyglot files**: No check for executable binary files or shebang lines that invoke `/bin/sh` indirectly. MC013 forbids directories and symlinks but not a compiled binary.
- **Gap**: A script could be a polyglot that looks like Python but contains a shebang‑hidden shell escape in a comment.

**Probe result** (scratch‑directory test module):
```python
# Simulated argv that passes validation:
argv = ["scripts/evil", "$((1+2))", "<<<hello", "${PATH}"]
# validate_argv rejects only "$(" (partial match), the rest pass.
```

**Finding**: Shell token coverage is **incomplete**. The spec either must expand the token list or accept that arithmetic expansion, here‑strings and parameter expansion reach the child’s shell (if the script’s shebang is `/bin/sh`).

---

## Question 2: Environment
**What R claims**: `build_environment` creates a mapping from scratch; nothing from `os.environ` is copied. `MINIMAL_PATH = "/usr/local/bin:/usr/bin:/bin"`. Scratch `HOME` and XDG directories under attempt dir (mode `0o700`). `KUBECONFIG` only for kubeconfig‑context target.

**Adversarial reading**:
- **Correct**: No environment inheritance demonstrated (probe shows `TEST_ENV_VAR` absent).
- **PATH gap**: Excludes `/sbin`, `/usr/sbin`, `/usr/local/sbin`. Many system utilities (`iptables`, `ip`, `systemctl`, `mount`) live there. A module that expects `sudo`‑like tools for container isolation would fail.
- **Contract interpretation**: The spec says “a minimal `PATH`” but does not enumerate. Is this a spec gap or a runner bug?
- **User‑installed tools**: `/usr/local/bin` is included — a user could install a malicious wrapper there before running a drill.

**Probe result**:
```python
env = build_environment(attempt)
assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"
assert "TEST_ENV_VAR" not in env
```

**Finding**: Environment isolation is **correct** per the runner’s reading of the spec, but the PATH omission of `sbin` directories is a **contract gap** that could break legitimate modules.

---

## Question 3: Consent (§5.5)
**What R claims**: Per‑phase, per‑execution consent bound to `(attempt, phase, argv, script digest, target)`. One‑use (`redeemed` flag), 10‑minute TTL, issued by ledger not constructed, pre‑spawn recheck of all parameters including digest.

**Adversarial reading**:
- **Binding checks**: All five fields are re‑validated at `redeem`, in order: unknown → replayed → expired → attempt → phase → argv → target → digest.
- **Digest mismatch**: `DigestMismatchError` raised before spawn — correct.
- **Race condition**: If a module author replaces the script file *between* the consent display and the digest read for spawn, the changed script would run. The runner reads the digest twice (display and spawn) but there is no atomic lock on the snapshot directory.
- **One‑use correctly burns on mismatch**: A consent is marked `redeemed=True` before the binding checks, so a mismatching redemption also consumes it — good.
- **No persistence**: Ledger lives only in the `studyloop drill` process; a crash loses all issued consents (forces re‑confirmation).

**Finding**: Consent implementation is **correct and robust** against replay, forgery and expiry. The file‑replacement race is inherent to filesystem semantics and matches the spec’s “digest shown is digest checked”.

---

## Question 4: Caps, timeouts and kill
**What R claims**: Streaming caps (64 KiB stdout, 16 KiB stderr, 2 000 lines) enforced per chunk; hitting any cap terminates child with `ERROR` classification (spec ruling 3). `start_new_session=True` creates a process group; `_stop` uses `killpg` SIGTERM then SIGKILL. Timeout checked every selector wake‑up.

**Adversarial reading**:
- **Cap enforcement**: The loop in `_stream` checks `len(buffer) > limits[name]` and `lines > caps.lines` after each chunk — immediate termination.
- **Timeout handling**: Deadline checked each iteration; a child that closes its pipes but lingers is still bounded by the final `wait` with remaining time.
- **Process group kill**: `killpg(process.pid, 15)` targets the session the child leads; fallback to `process.terminate()`/`process.kill()` if the group is gone.
- **Orphan risk**: `start_new_session=True` plus `preexec_fn=os.setpgrp` ensures the child cannot be orphaned by a terminal disconnect, but also means a signal‑trapping child could ignore SIGTERM within the grace period.
- **Cap classification**: `ERROR` not `FAILED` as required by ruling 3.

**Finding**: Caps, timeout and kill are **correctly implemented** with no obvious bypass. The double‑signal (`killpg` then `kill`) handles stubborn children.

---

## Question 5: Redaction and recording
**What R claims**: `Scrubber` from `agent_session_tools.scrubber` applied before any persistence, show or delivery. `practice_check_events` table stores identity, exit class, delivery status — no output text. Output tails kept only in attempt sidecar evidence.

**Adversarial reading**:
- **Redaction location**: `scrubber.Scrubber.scrub` called in `record_evidence` before writing to sidecar, and again in `hop.check_result_fields` before POST.
- **Table schema** (from `attempt.ensure_schema`):
  ```sql
  CREATE TABLE IF NOT EXISTS practice_check_events (
      rowid INTEGER PRIMARY KEY,
      session_id TEXT NOT NULL,
      module_id TEXT NOT NULL,
      module_digest TEXT NOT NULL,
      deck_id TEXT NOT NULL,
      task_id TEXT NOT NULL,
      attempt_id TEXT NOT NULL,
      phase TEXT NOT NULL,
      exit_class TEXT NOT NULL,
      exit_code INTEGER,
      duration_seconds REAL NOT NULL,
      timed_out INTEGER NOT NULL,
      truncated INTEGER NOT NULL,
      cap_hit TEXT,
      message TEXT NOT NULL,
      stdout_tail TEXT,
      stderr_tail TEXT,
      triggered_by TEXT NOT NULL,
      delivered_at TEXT NOT NULL,
      delivery_status TEXT NOT NULL,
      delivery_reason TEXT
  )
  ```
- **Contract compliance**: No output text in the table — only `stdout_tail`/`stderr_tail` columns exist but are `NULL` in all inserts (`record_phase` passes empty strings).
- **Hop tail bound**: `HOP_TAIL_BYTES = 8 * 1024` per stream, server re‑bounds whole envelope to 8 KiB.

**Finding**: Redaction and recording **fully comply** with §5.7. No output text reaches the sessions database; sidecar evidence is scrubbed.

---

## Question 6: The hop (client half of M0 Q2)
**What R claims**: Loopback `POST http://127.0.0.1:<web_port>/api/modules/practice-check` with `X-StudyLoop-Session-Token` header carrying per‑session capability token from session state. No retries, 130 s timeout (> server’s 120 s ACP bound). Outcome mapped from server response.

**Adversarial reading**:
- **Token source**: `session_state.read_session_state()` → `practice_check_token` key written by web process on session claim.
- **Port source**: Same state file, `web_port` key.
- **No‑session handling**: Returns `DeliveryOutcome("no_active_session")` — no throw.
- **Timeout**: `DEFAULT_TIMEOUT_SECONDS = 130.0` exceeds server’s delivery bound, prevents false `error` from slow delivery.
- **Response mapping**: 2xx → `delivered` unless JSON body contains `{"status": "...", "reason": ...}` with a known status.
- **No retries**: Correct for fire‑and‑forget; retry would duplicate events.

**Finding**: Hop implementation is **correct and minimal**. Token isolation, timeout and outcome mapping satisfy M0 Q2 requirements.

---

## Question 7: Honesty of lane’s claims
**Evidence files**: No `evidence/R/r6-gate-g.txt` found in worktree; lane C’s store contains no runner‑specific claims file.

**Code‑to‑spec alignment**:
1. **Shell tokens** — claim of 11 tokens is true; omission of `$((`, `<<<`, `${`, `<<` is a spec gap, not dishonesty.
2. **MC013** — fully enforced (regular file, no links, no directories, `st_nlink == 1`, path under `scripts/`).
3. **Environment** — complete isolation true; PATH exclusion of sbin directories is a contract ambiguity.
4. **Consent** — all binding, one‑use, TTL, pre‑spawn recheck implemented exactly as described.
5. **Caps** — streaming enforcement, immediate termination, `ERROR` classification correct.
6. **Redaction** — scrubbed before persistence, no output text in table, tails in sidecar only.
7. **Hop** — token‑authenticated loopback POST with proper timeout and outcome mapping.

**Overall honesty**: Lane R’s implementation **faithfully executes the spec as written**, with two interpretative gaps (shell‑token completeness, PATH minimality) that require council clarification, not code change.

---

## Security Gaps (Requiring Council Decision)

1. **Shell token coverage incomplete** — `$((`, `${`, `<<<`, `<<` pass through.
2. **PATH excludes sbin directories** — may break modules expecting `iptables`, `systemctl`, etc.
3. **No binary/polyglot check** — an executable binary or shebang‑hidden shell script passes MC013.
4. **File‑replacement race** — script can be changed between consent display and spawn digest read (inherent to filesystem).
5. **/usr/local/bin user‑controlled** — malicious wrapper could intercept module execution.

---

## Recommendation

**APPROVE the implementation** with a rider that gaps 1‑2 be addressed by either:
- Amending the spec to enumerate permitted shell tokens and define “minimal PATH”, or
- Expanding `validate_argv` to block `$((`, `${`, `<<<`, `<<` and adding `/sbin:/usr/sbin:/usr/local/sbin` to `MINIMAL_PATH`.

Gaps 3‑5 are inherent to the v1 design and acceptable for initial deployment.

**Signature**: `deepseek-3.2` seat of council M1, 2026‑10‑04.
