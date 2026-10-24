## ADDED Requirements

### Requirement: Drill phases run as argv without a shell, in a clean environment, inside an immutable snapshot
Each drill phase (`setup`, `check`, `cleanup`) SHALL name one executable under the module
snapshot's `scripts/` plus literal arguments; the runner SHALL execute it with `shell=False` from
the snapshot, in an environment built from scratch (a scratch `HOME`, a per-attempt working
directory, `STUDYLOOP_DRILL_ID` from the deck and task ids, the target's injected variables) and
never the caller's inherited environment.

#### Scenario: the environment is not inherited
- **GIVEN** the caller's environment carries `STUDYLOOP_SECRET_PROBE=1`
- **WHEN** a check phase runs a script that prints its environment
- **THEN** the variable is absent from the captured output

### Requirement: A drill phase with shell tokens, a script outside `scripts/` or over 64 arguments is refused before spawn
A phase whose command contains shell tokens (`;`, `|`, `&`, `&&`, `||`, `$(`, backtick, `>`, `<`,
newline), names an executable that is not a regular file directly under the snapshot's `scripts/`
(a regular file elsewhere in the snapshot, a symlink or hardlink leaving `scripts/`, an absolute
path, a directory), or whose argv exceeds 64 arguments SHALL be refused before any process starts.

#### Scenario: a shell token is refused
- **GIVEN** a check phase whose argv contains `;`, `|`, `&`, `&&` or `$(`
- **WHEN** `studyloop drill check <module>/<deck>/<task>` runs
- **THEN** it refuses before spawning and names the token

#### Scenario: a regular file outside scripts/ is refused
- **GIVEN** a check phase naming `decks/helper.sh`, a regular file inside the snapshot but outside `scripts/`
- **WHEN** the phase is consented to
- **THEN** it is refused before spawn (MC013 at runtime) naming the path

### Requirement: Every phase is consented to on its exact argv and script digest, each time
Before each phase the runner SHALL show the phase, target, exact argv and the content digest of
the script, require an explicit confirmation, and re-check the digest at spawn; a change between
confirmation and spawn SHALL abort. A CLI confirmation SHALL expire 10 minutes after it is given
and SHALL be usable once. Setup and cleanup SHALL each be consented to separately from
check. The web surface SHALL expose no `--yes` equivalent in v1.

#### Scenario: a modified script does not run
- **GIVEN** consent given on digest `A`
- **WHEN** the script's content changes before spawn
- **THEN** the phase aborts and reports the digest mismatch

### Requirement: Exit classes, per-phase timeouts and streamed caps are the runner's, not the module's
For `check`, exit `0` SHALL mean passed; `1` SHALL mean "failed, task not complete"; `≥ 2` SHALL mean
the check could not run. For `setup` and `cleanup`, any non-zero exit SHALL be classed as an error
that is logged and surfaced; a failed cleanup SHALL still close the attempt. `timeoutSeconds`
SHALL bound each phase separately and a timeout SHALL be an error, never a fail.

#### Scenario: a failing cleanup still closes the attempt
- **GIVEN** a cleanup script that exits `3`
- **WHEN** the cleanup phase runs with consent
- **THEN** the phase is classed as an error, the message is shown to the learner, and the attempt is closed

### Requirement: Drill output is capped while it streams and kept only as redacted transient evidence
Output SHALL be
streamed with caps enforced while the process runs — 64 KiB of stdout, 16 KiB of stderr, 2,000
lines in total — and when a cap is hit the process SHALL be terminated, `truncated` recorded, and
the phase classed as an error naming the cap (a check that floods its output is not a trustworthy
pass). Output SHALL be redacted by the existing secret detector and kept only as transient evidence.

#### Scenario: output is capped while streaming
- **GIVEN** a check script that prints 10 MiB
- **WHEN** it runs
- **THEN** the captured output stops at the cap, the process is terminated, and the result is an error naming the cap

### Requirement: A passing check records no learner observation
A drill check result SHALL be recorded as a transient `practice_check` event only — one row per
phase completion in a `practice_check_events` table of the sessions database keyed by attempt id,
holding identity, phase, exit class, duration, truncation flags and the delivery outcome; it SHALL
NOT write a `confident` or `struggling` observation into learner history. Mastery still comes from
teach-back.

#### Scenario: no observation after a passing check
- **GIVEN** an empty learner history
- **WHEN** a check phase exits `0`
- **THEN** `study_progress` and the observation store are unchanged and one `practice_check` event exists

### Requirement: `studyloop drill` is the MVP's only execution surface
`studyloop drill <setup|check|cleanup> <module>/<deck>/<task>` SHALL be the only way a module phase
is executed in v1; the web UI SHALL list and start drills but SHALL NOT execute a phase. The drill
SHALL run inside the learner's one claimed session.

#### Scenario: the scaffold's offline drill runs end to end
- **GIVEN** the module `studyloop module new` produces, installed with `module add`
- **WHEN** `drill setup`, `drill check` and `drill cleanup` run with consent
- **THEN** each exits `0` without Docker, kind or network

### Requirement: A kubeconfig-context attempt runs against a core-created disposable cluster
For a module whose `target.kind` is `kubeconfig-context`, core SHALL create a disposable kind
cluster named from the attempt id (prefix `studyloop-`) before the `setup` phase, write a
kubeconfig containing exactly that one context into the attempt directory (mode `0600`), and
export it as `KUBECONFIG` to every phase; the cluster SHALL be deleted after `cleanup` and on
every failure path after it was created.

#### Scenario: the drill's cluster is disposable and the learner's clusters survive
- **GIVEN** a learner with an existing kind cluster and a kubeconfig-context module
- **WHEN** `setup`, `check` and `cleanup` run for one attempt
- **THEN** a `studyloop-*` cluster existed only between `setup` and `cleanup`, every phase saw
  `KUBECONFIG` naming only that cluster, and the learner's cluster is untouched

### Requirement: Disposable cluster — core never touches a cluster it did not create and refuses a name collision
Core SHALL never use, list-and-delete, or modify a
cluster it did not create for that attempt. A name collision SHALL be refused, never reused.

#### Scenario: a cluster already carrying the attempt's name is refused, not reused
- **GIVEN** a kind cluster that already carries the name derived from the attempt id
- **WHEN** core provisions the attempt's cluster
- **THEN** it refuses naming that cluster, the only `kind` call made was a read-only cluster listing, and no kubeconfig was written

### Requirement: Disposable cluster — every failure path deletes it and a teardown failure is never hidden
A
teardown failure SHALL be reported as an error naming the cluster, never hidden.

"Every failure path" means: any `check` result in an error class (exit status 2 or above, a
timeout, an output cap) and any `setup` result other than pass delete the cluster and close the
attempt; only a `check` that exits `1` (task not complete) keeps it for the next try.

#### Scenario: a check that errors tears the cluster down; a check that fails does not
- **GIVEN** a kubeconfig-context attempt with its cluster
- **WHEN** `check` exits `1`
- **THEN** the cluster and the attempt stay open for the next try
- **WHEN** `check` instead times out, is capped, or exits `2` or above
- **THEN** the cluster is deleted and the attempt is closed with the reason recorded

### Requirement: Disposable cluster — after a failed create, core deletes only a cluster it can prove it made
After a
`kind create` that did not succeed, core SHALL delete the cluster only when it can prove it created
it — kind wrote the attempt's own kubeconfig naming that cluster — and SHALL otherwise report the
name and the exact by-hand command without deleting anything.

#### Scenario: a failed create never deletes a cluster core cannot prove it made
- **GIVEN** `kind create` fails before it wrote the attempt's kubeconfig
- **WHEN** core reports the failure
- **THEN** no `kind delete` runs and the error names the cluster and the by-hand command

### Requirement: Disposable cluster — a failed delete keeps the kubeconfig and any exception after create still tears down
When a delete fails, the attempt's
kubeconfig SHALL be kept and the reported command SHALL name it (`kind delete cluster --name <name>
--kubeconfig <attempt>/kubeconfig`), so the learner never has to touch their default kubeconfig.
Any exception after a successful create — not only the runner's own errors — SHALL run the same
teardown and keep the original error.

#### Scenario: a failed delete keeps the attempt's kubeconfig and names it in the by-hand command
- **GIVEN** kind wrote the attempt's kubeconfig, the create then failed, and the follow-up `kind delete` fails too
- **WHEN** core reports the failure
- **THEN** the attempt's kubeconfig is still a file and the message carries `kind delete cluster --name <name> --kubeconfig <attempt>/kubeconfig`

### Requirement: Disposable cluster — core's own `kind` runs with an allowlisted environment
Core's own `kind` invocation SHALL run with an allowlisted
environment (HOME, PATH, TMPDIR, locale, Docker, kind, proxy and certificate variables), never the
learner's whole environment and never `KUBECONFIG`.

#### Scenario: kind sees the allowlisted variables and nothing else
- **GIVEN** a parent environment carrying unrelated secrets and `KUBECONFIG` beside Docker, kind, proxy, certificate and locale variables
- **WHEN** core creates the attempt's cluster
- **THEN** every `kind` invocation sees the allowlisted variables and neither the secrets nor `KUBECONFIG`

### Requirement: Disposable cluster — a refusal before consent opens no attempt record and a non-canonical record is rejected
A phase refused before consent (no cluster for a
`check`, a missing core tool) SHALL open no attempt record. An attempt record whose id, directory
or kubeconfig path is not the canonical one for its file SHALL be rejected, never used to delete.

#### Scenario: a missing kubeconfig is refused before spawn
- **GIVEN** a kubeconfig-context attempt whose kubeconfig was not written by core
- **WHEN** a phase is about to spawn
- **THEN** the runner refuses with an error and nothing runs
