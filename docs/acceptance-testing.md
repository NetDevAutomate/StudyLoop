# Acceptance testing

StudyLoop's acceptance tier is modelled directly on the [AWS Terraform
Provider's `make testacc`](https://github.com/hashicorp/terraform-provider-aws) —
every acceptance test **skips with a clear reason** unless you explicitly opt
in, and once you opt in, a test that cannot run for a nameable reason (a
missing binary, a missing credential) still skips by name rather than
failing or hanging. What differs once you *are* opted in: an unknown
selection value (a harness or actor name that does not exist) is a loud
failure, never a silent no-op — see "Rules that keep the tier honest" below.

## Where it sits in the test pyramid

| Layer | Marker / recipe | Proves | Needs |
| --- | --- | --- | --- |
| Unit | `just test` | Logic, contracts, protocol conformance | Nothing external |
| Integration | `pytest -m integration` | Real tmux/SQLite | tmux installed |
| Browser (e2e) | `just e2e` | Web UI journeys against fake agents | Playwright Chromium |
| **Acceptance** | `just testacc` | A **real** harness through the real product surface, a deterministic scripted learner, a disposable scratch env | `STUDYLOOP_ACC=1`; the harness's real binary; opt-in, never runs in CI |
| UAT (sign-off) | `STUDYLOOP_UAT=1` under `tests/acceptance/uat/` | Browser journeys + pedagogy graded against a written rubric, for a release sign-off | Its own opt-in on top of acceptance (`just testuat`); see "The UAT (sign-off) tier" below |

Acceptance sits between the browser suite (which fakes the agent) and UAT
(which grades pedagogy). Its job is narrower than either: prove the real
product, driven by a real coding-harness binary, produces the artefacts a
learner's session should — with nothing standing in for the mentor.

## Every environment variable

| Variable | Meaning | Default when unset |
| --- | --- | --- |
| `STUDYLOOP_ACC` | Must be exactly `1` or every acceptance test skips, naming this variable and this file | unset (tier is off) |
| `STUDYLOOP_ACC_HARNESS` | Comma list of harnesses to run (`kiro,codex,claude,opencode,pi,grok`) | unset → **all six** |
| `STUDYLOOP_ACC_ACTOR` | Which learner backend drives the conversation (see "The learner actors" below) | unset → `scripted` |
| `STUDYLOOP_ACC_REAL_AUTH` | Exactly `1`: the harness keeps your **real** home and credentials while every StudyLoop pointer stays scratch (see "Real harness auth" below) | unset → scrubbed scratch HOME, no credentials |
| `LITELLM_API_KEY` | `ACTOR=gateway`: the key for your LiteLLM proxy | unset → `gateway` skips, naming it |
| `LITELLM_BASE_URL` | `ACTOR=gateway`: your proxy's address | unset → `http://127.0.0.1:4000` |
| `STUDYLOOP_ACC_GATEWAY_MODEL` | `ACTOR=gateway`: which alias behind the proxy plays the learner | unset → `gateway` skips, naming it |
| `STUDYLOOP_ACC_DIRECT_PROVIDER` | `ACTOR=direct`: a `provider_profiles` slug (`openai`, `openrouter`, `gemini`, `anthropic`) | unset → `openai` |
| `STUDYLOOP_ACC_DIRECT_MODEL` | `ACTOR=direct`: a curated model id within that provider | unset → the provider's cheapest curated model |
| `STUDYLOOP_ACC_HARNESS_ACTOR_CMD` | `ACTOR=harness`: the command that launches the second harness | unset → `harness` skips, naming it |
| `STUDYLOOP_UAT` | The UAT tier's own, additional opt-in ON TOP OF `STUDYLOOP_ACC=1` (both must be `1`) | unset (tier is off) |
| `STUDYLOOP_UAT_EVIDENCE_ROOT` | Overrides the UAT tier's durable evidence root (council D-14) | unset → `~/.local/share/studyloop/uat/<run-id>/` |

An unknown value in `STUDYLOOP_ACC_HARNESS` or `STUDYLOOP_ACC_ACTOR` **fails
the run**, naming the bad value and the known set — it is a typo you made,
not something to skip past quietly. A *missing credential* is the opposite
case and skips by name: see "Credentials: skip by name, never fail" below.

## Running it

`just` recipe parameters are **positional**, not `KEY=value` the way a
`make` variable assignment would be — there is no such syntax in `just`.
`just testacc HARNESS=kiro` does **not** set `HARNESS`; it passes the
literal string `"HARNESS=kiro"` as the *first* positional argument. Invoke
positionally:

```bash
just testacc                                    # all six harnesses, scripted actor
just testacc kiro                               # just Kiro, scripted actor
just testacc kiro scripted tests/acceptance/test_kiro_web_acp_lane.py
```

The one table that maps every positional argument to what it actually sets:

| Position | `just` parameter | Env var / effect | Default when omitted |
| --- | --- | --- | --- |
| (always) | — | `STUDYLOOP_ACC=1` | n/a — the recipe always sets this |
| 1st | `HARNESS` | `STUDYLOOP_ACC_HARNESS` | `""` → all six harnesses |
| 2nd | `ACTOR` | `STUDYLOOP_ACC_ACTOR` | `"scripted"` |
| 3rd | `TESTS` | passed straight through as the pytest path argument, not an env var | `packages/studyloop/tests/acceptance/` |

The recipe sets `STUDYLOOP_ACC=1` for you; it is the one place you don't set
that variable by hand. Under the hood it is:

```bash
STUDYLOOP_ACC=1 STUDYLOOP_ACC_HARNESS="<harness>" STUDYLOOP_ACC_ACTOR="<actor>" \
    uv run --group dev pytest -m acceptance \
    --ignore=packages/studyloop/tests/acceptance/uat <tests>
```

Without `STUDYLOOP_ACC=1`, `just test` (and CI) never see these tests at
all — the `acceptance` marker is deselected by default in **both**
`pyproject.toml` files, the same pattern already used for `integration`,
`e2e` and every `live_*` marker.

`--ignore=.../acceptance/uat` is permanent, not a placeholder: `tests/acceptance/uat/`
is reserved for the UAT (sign-off) tier's own additional opt-in
(`STUDYLOOP_UAT=1`, a later lane's contract) and a plain `testacc` invocation
must never collect it, even once real tests land there — see "Where it sits
in the test pyramid" above.

## Subprocess isolation, not an in-process monkeypatch

`studyloop.settings.CONFIG_DIR` binds `Path.home() / ".config" / "studyloop"`
**at import time**. Monkeypatching `HOME` in the test process after
`studyloop.settings` has already been imported does nothing — the module
level constant does not move, and a test that thinks it is isolated is
actually reading and writing the real config directory.

Every acceptance test therefore drives the product through a **subprocess**,
built with a sanitized environment *before* that subprocess ever imports
`studyloop`:

- `tests/acceptance/isolation.py` builds a fresh scratch `HOME`, a
  `STUDYLOOP_STATE_DIR` under it, and a seeded config dir — all under the
  pytest `tmp_path` for that one test.
- `studyloop.session.child_env.build_scratch_child_env()` layers the usual
  credential-scrubbing (`build_child_env`) with an override of `HOME`,
  `STUDYLOOP_STATE_DIR`, and every `XDG_*` base directory — so a harness
  binary that reads `XDG_CONFIG_HOME` directly, rather than deriving a path
  from `HOME`, still lands under the scratch tree. `build_child_env`'s own
  deny-list additionally strips `STUDYLOOP_TEST_ACP_CMD`/`STUDYLOOP_TEST_AGENT_CMD`
  — a stale export left in a developer's shell must never let an agent child
  re-enter the stub-agent test hatch instead of the real mentor binary.
- Every scratch env also gets its own `TMUX_TMPDIR`, under the scratch tree —
  a dedicated tmux socket directory per run, so a live tmux-driven lane can
  never attach to a shared server started under the developer's real
  environment. `create_scratch_environment` registers a `tmux kill-server`
  descendant stopper scoped to that socket, run before the sweeper ever
  touches the filesystem.
- The scratch child sees **no inherited `STUDYLOOP_*` pointer** except the
  `STUDYLOOP_STATE_DIR` the builder sets itself, and no `SESSION_CONTEXT_SCOPE`.
  Found by the first live run (2026-09-16): the unit suite's root conftest
  sets `STUDYLOOP_SESSION_DIR`/`STUDYLOOP_DB`/`SESSION_CONTEXT_SCOPE` in the
  pytest process, and a child that inherited them wrote `session-state.json`
  into the *suite's* throwaway dir while the lane waited for it under the
  scratch config dir — every harness timed out before its binary was looked at.
- The seeded `config.yaml` carries `memory.default_scope: unclassified`
  alongside `topics: []`. Same first live run: the context-memory scope policy
  never infers a scope, so a scratch without one is a fresh install on which
  `studyloop study` exits 2 ("No context scope configured") before any harness
  launches.

### Real harness auth (opt-in, `STUDYLOOP_ACC_REAL_AUTH=1`)

The scrubbed scratch HOME hands the harness binary **no credentials at all**:
`pi` printed "No API key found" for all three scripted turns on the first live
run while the lane still passed mechanically (a real session started, three
prompts produced pane changes, the session ended and resumed cleanly). That
proves the launch plumbing and nothing about the model path — and no harness
whose credentials live under its home (all six) can ever do better there.

`STUDYLOOP_ACC_REAL_AUTH=1` is how a developer certifies a harness's real
model path **on their own machine**: `isolation.build_real_harness_auth_env`
keeps `HOME`, `XDG_*` and every provider credential the shell exported — the
same environment `studyloop study` gets in a real terminal (the CLI/tmux
production path inherits the shell env unscrubbed, `session/orchestrator.py`),
so this is production-faithful, not a relaxation of a production control —
while **every StudyLoop pointer is still scratch**: `STUDYLOOP_CONFIG` (the
seeded config, incl. its scope), `STUDYLOOP_SESSION_DIR` (session-state.json,
the one-session authority), `STUDYLOOP_STATE_DIR`, `STUDYLOOP_DB`, and the
run's own `TMUX_TMPDIR`. The evidence bundle records `auth_mode: real-auth`
so a reader can tell such a run from a `presence-only` one without opening
`turns.json`.

What it costs and touches, said plainly: the harness **will** bill its
configured provider for the scripted turns, and it **will** write its own
transcripts into its real directories (`~/.pi/agent/sessions`,
`~/.local/share/opencode/storage`, `~/.grok/sessions`), exactly as any real
session does. The guarded sweeper never touches those; it only ever removes
the scratch tree. Never the default, never set by any `just` recipe, never
appropriate in CI.

`scripts/harness-evidence.py <harness> --real-auth …` is the recorded,
re-runnable form used for issue #21's per-harness evidence receipts; item 1
(install into a scratch HOME) always runs in the scrubbed mode regardless.
For `grok` it also sets `STUDYLOOP_GROK_TRUST_SESSION_DIR=1` — an unattended
session cannot answer Grok's directory-trust dialog — and the entries that
pre-write adds to the real `trusted_folders.toml` are removed after the run.

## The guarded sweeper

Every scratch tree is disposable, and the sweeper that disposes of it is
**guarded, not trusting**. Before it ever calls `shutil.rmtree`, it hard-errors
(never silently skips) if:

- the scratch home resolves to, or under, the **real** home;
- the real home resolves to, or under, the scratch home (the reverse case —
  a scratch tree accidentally rooted so it contains the real one);
- the scratch config dir resolves to, or under, the real `~/.config/studyloop`;
- the ownership sentinel — a random token written into the scratch tree at
  creation — is missing or does not match.

Every check resolves symlinks first, so a scratch home that is *itself* a
symlink escaping back to the real tree trips the same guard a literal path
would. A guard failure is a hard error: the scratch tree is left in place for
inspection, never swept "just in case." See
`tests/test_acceptance_isolation.py` for the escape-canary test that proves a
full create-then-sweep lifecycle never touches a planted file outside the
scratch tree.

## The learner actors

The learner side of an acceptance conversation is **pluggable**: four
backends behind one test-side protocol (`tests/acceptance/actors/`). The
mentor side is **never** simulated in a live acceptance test — hermetic
plumbing tests that fake the mentor are the one named exception, and they
say so.

| Actor | What plays the learner | Needs | Cost per run |
| --- | --- | --- | --- |
| `scripted` | An ordered, versioned turn script — no LLM at all | Nothing (the CI-safe default) | Free |
| `gateway` | A model alias behind your local LiteLLM proxy | `LITELLM_API_KEY` + `STUDYLOOP_ACC_GATEWAY_MODEL` | Priced by the alias, capped by the budget guard |
| `direct` | OpenAI or Anthropic's own API, no proxy in the middle | the provider's own key (e.g. `OPENAI_API_KEY`) | Priced by the model, capped by the budget guard |
| `harness` | A second coding-harness process, over its own tmux socket | `tmux` + `STUDYLOOP_ACC_HARNESS_ACTOR_CMD` | Whatever that harness's own subscription charges — **not observable from here** |

Every actor returns the same normalized result: a transcript of
`(learner_message, mentor_reply, usage)` turns plus one explicit
termination outcome — `completed`, `budget-exhausted`, `cancelled`, or
`errored`. **A transcript is always captured**, on every outcome including
the failures: an actor never raises for an expected condition, so partial
evidence from a run that went wrong is still there to grade.

`CardGenerator` (`studyloop.content.generators`) is deliberately *not*
reused: it is a flashcard protocol, and a conversation is not a deck. The
actors follow the same repo idiom — a `runtime_checkable` Protocol plus a
factory keyed off a config value — with conversation-shaped members.

### Token accounting is honest, never guessed

`usage` reports `None` — not `0` — where a backend genuinely cannot observe
a count. `ACTOR=harness` gives terminal output, not tokens, so it reports
unknown for every turn. `ACTOR=scripted` reports `0`, which is the *true*
figure: there is no model on the learner side to spend anything.

### The budget guard: max turns AND max output tokens

Every LLM-backed actor is capped on both, and the cap is a **hard abort**,
not a warning. The check happens *before* a turn starts, so a run never pays
for a turn it then discards; hitting either cap ends the conversation with
`budget-exhausted` and the transcript so far.

This is load-bearing rather than defensive: an LLM learner has no
natural-completion signal in this tier — nothing decides "the student seems
satisfied, stop" — so **the budget guard is what ends a `gateway`/`direct`
conversation**. A run that ends `budget-exhausted` is the normal case, not a
failure. Turning the model's own "I'm done" into a stop condition is a
judgement call left to the lane that owns rubric judging.

An unknown output-token count is never counted against the cap (an unknown
spend is not assumed to be zero, but it is not treated as a violation
either) — which means `ACTOR=harness` is effectively capped on turn count
alone. That is the honest consequence of not being able to see its usage.

### Credentials: skip by name, never fail

A missing key or binary is a **named skip**, never a failure and never a
prompt: `gateway` without `LITELLM_API_KEY` skips saying exactly that.
Every backend is asked whether it can run *before* anything constructs it,
so an absent credential never surfaces as an exception from a constructor.

An unknown `STUDYLOOP_ACC_ACTOR` value is still a loud failure — a typo is
not a reason to skip.

### `ACTOR=gateway` reads its address from the environment

The gateway backend is not a `provider_profiles` registry row, for the
reason [`contributing.md`](contributing.md) already gives: a registry row's
base URL is fixed in code, and a per-machine proxy address needs an
environment override the registry does not have. So `gateway` reads
`LITELLM_BASE_URL` (defaulting to the proxy's usual local address) directly.
Never commit a gateway hostname, port or key.

### `ACTOR=direct` reuses the provider registry's *data*

`direct` resolves its base URL, auth variable and curated model list through
`provider_profiles` — the vendor endpoints are already curated there — but
issues a plain chat/messages call rather than the forced-tool-call shape card
generation uses. Only the two generic HTTP adapters are supported,
`openai_compat` and `anthropic_compat`; `bedrock` (boto3/SigV4) and `ollama`
(local, keyless) are out of scope for a backend that exists specifically for
"I have a vendor API key but no gateway".

### `ACTOR=harness` gets its own tmux socket

A second harness process must never share a tmux server with the mentor's,
or with one started under your real environment, so this backend requires its
own socket directory and passes `TMUX_TMPDIR` explicitly on every tmux call —
it never mutates the test process's own environment.

One practical constraint it now reports clearly rather than failing
cryptically: a unix socket path is capped at 104 bytes on macOS, and a
directory under pytest's `tmp_path` exceeds that. Pass a short directory; the
error names the limit and the fix.

### The scripted actor

`ACTOR=scripted` drives the **mentor** through an ordered, versioned turn
script rather than a live LLM on the learner side (`tests/acceptance/turn_script.py`).
A turn script is plain data:

```json
{
  "version": 1,
  "turns": [
    {"prompt": "In one sentence, what is a Python decorator?"},
    {"prompt": "And a closure?"}
  ]
}
```

The loader is strict: an unknown top-level or per-turn field is a loud
`TurnScriptError`, not a silently-ignored key, and the format is versioned so
a future incompatible shape is rejected by name rather than misread.

`expect_contains` / `expect_not_contains` are **reserved, not yet honoured**:
the format accepts them as known per-turn fields so a future turn-runner's
shape is already settled, but no executor evaluates them anywhere in this
lane yet — setting either to a non-empty list raises `TurnScriptError` rather
than silently accepting a predicate nothing checks. Leave them unset until a
later lane wires an executor through the field.

The mentor side (the real harness binary) is **never** mocked in a live
acceptance test — only the learner's turns are scripted. Hermetic plumbing
tests that mock the mentor exist too, and are named as such, so nobody
mistakes one for the other.

## The first lane: Kiro over the web ACP path

`tests/acceptance/test_kiro_web_acp_lane.py` is the first end-to-end proof:
`STUDYLOOP_ACC=1` plus a signed-in `kiro-cli` on `PATH` starts a real
`studyloop web` server against a scratch environment, opens a real ACP
session with the study persona, sends the scripted turns, and asserts the
assistant answered each one before the session ends cleanly. Missing
`kiro-cli`, or a `kiro-cli whoami` that fails, is a **named skip** — the
reason states which binary or step was missing, never a bare "skipped."

The availability probe runs `kiro-cli whoami` under the **same scratch HOME**
the server (and the kiro-cli child it spawns) will actually get, not the
test process's real environment: kiro-cli's credential store is
HOME-derived, so a machine authenticated in the real HOME but not under a
fresh scratch HOME must skip, naming that, rather than pass the probe and
then hang for the full reply timeout once the live session never answers.
`STUDYLOOP_ACC_HARNESS` also gates this lane directly — selecting anything
that does not include `kiro` (e.g. `just testacc codex`) named-skips it
before a scratch env or a browser context is ever built, so a run never
starts a real, billed Kiro session it was not asked to select.

The CLI/tmux path (all six harnesses, not just Kiro-over-web) is
`tests/acceptance/test_harness_matrix_live.py`, described in "The CLI/tmux
harness matrix" below. This lane's validators are mechanical (a real
session started, real turns were answered, the session ended without a
crash) rather than DB-row-level (topic/struggle rows, `session_search`
id-set membership, a written wind-down record) — those validators depend on
the session-memory schema and B4's evidence-writer wiring; see "Coverage
inventory" below for the exact tracked exclusion.

## The CLI/tmux harness matrix (all six harnesses)

`tests/acceptance/test_harness_matrix_live.py` extends the Kiro-over-web
proof above to every `RELEASE_HARNESSES` member over the CLI/tmux surface —
`E-B8` is where all six harnesses actually launch, not only Kiro. Coverage
is published as a **matrix** (harness × surface × transport), never a
single green check per harness (council D-19): see "Coverage inventory"
below.

For each harness, `STUDYLOOP_ACC=1 just testacc <harness>` drives
`studyloop study --agent <harness>` for real, under the same scratch-env +
tmux-socket isolation the rest of this document describes, then sends
**three or more** scripted turns (council D-21(2)'s floor), resumes the
ended session (D-21(2)'s "wind-down → resume"), and ends it again. Order
matters and is fixed, not alphabetical: `codex` and `claude` first (highest
real usage), then `kiro` over tmux (its web-ACP coverage above does not
certify the CLI path) and `pi` (core since 2026-09-16), then the PREVIEW
harnesses `opencode` and `grok` — never a blocker on the CORE four. `HARNESS_ORDER` in the test
module is a literal re-ordering of `RELEASE_HARNESSES`; the structural
guard that keeps the two from drifting apart — full order, length, no
duplicates, not just a set comparison — lives in
`tests/test_harness_matrix_live_mechanics.py`, **outside** the `acceptance`
marker, so it runs in every `just test`/CI invocation, not only under
`STUDYLOOP_ACC=1` (council D-19/D-26: a drift guard gated behind an opt-in
nobody sets in CI never actually guards anything).

The scratch tmux socket directory (see "Subprocess isolation" above) lives
under a short `/tmp`-rooted path, **not** under the scratch `HOME`: a
pytest `tmp_path`-rooted socket dir plus tmux's own `tmux-<uid>/default`
suffix can exceed AF_UNIX's 104-byte `sun_path` limit, at which point `tmux
new-session` fails outright ("File name too long") rather than merely
running slowly — see `tests/test_acceptance_isolation.py`'s regression
test. Every `TmuxHarness` this lane constructs against a scratch child is
built as `TmuxHarness(env=scratch_env.env)`, never a bare `TmuxHarness()`:
the latter addresses THIS test process's own `TMUX_TMPDIR`, not the
scratch child's, and would silently talk to the wrong (or no) tmux server
— see `tests/test_harness_matrix_live_mechanics.py`'s
`TestTmuxHarnessSocketWiring` for the CI-safe positive/negative control.

### Turn delivery and the budget guard

`tests/harness/drive.py`'s `PaneDriver` sends one scripted turn at a time to
the mentor's tmux pane and waits for a **reply** — not merely for the pane
to change, which a keystroke echo alone would satisfy — by requiring the
non-blank line count to grow past what a single echoed prompt line would
already account for. Every turn is budget-guarded two ways: a per-turn
timeout and a total max-turns ceiling (grok F9), so a runaway harness (a
hang, a silent failure, an auth prompt nothing answers) is cut off as
`TurnBudgetExceededError` rather than hanging the run. On a timeout, the
pane is still captured and appended to `driver.records` *before* the
exception is raised — the evidence bundle below is written from the outer
`finally`, so a run that never gets past the FIRST wait (session state,
tmux session, or pane children) still produces a bundle, not silence.
Unit-tested in `tests/test_harness_drive.py` against a scripted `sh`
"harness" — never a real coding-agent binary — including the
runaway-harness cutoff case and the timeout-still-records-a-turn case.

### Availability probes (per-harness quirks as fixtures)

Every harness gets a **named skip** when its binary is missing (D-13). Only
`kiro` has a verified, side-effect-free "authenticated under THIS scratch
HOME" probe (`kiro-cli whoami`, the same check the web-ACP lane above uses);
the other five fall back to a presence-only check — see "Coverage
inventory" for why that is a tracked exclusion rather than a silently
weaker guarantee. Probes live in a `PROBES` dict keyed by harness name, not
an `if`/`elif` chain inside the test body, so adding a real probe for a
sixth harness is a one-line addition, not a body rewrite.

### Evidence (minimal, pending B4)

Every driven run writes a small evidence bundle via
`tests/acceptance/evidence.py`: a `manifest.json` (run id, harness, actor,
outcome, turn count, and — council D-21(7) — `platform`/`auth_mode`/
`harness_version`, each recorded as `null` when unknown rather than simply
absent) plus a `turns.json` capturing each turn's prompt, pane output, and
elapsed time — pane text is **evidence attached to the bundle**, never
itself an assertion target (D-17). The run id carries a random suffix
(`secrets.token_hex(4)`), not just second-granularity `time.time()`, so two
runs finishing within the same wall-clock second never collide and mask a
real failure with a `FileExistsError` from inside the bundle-writer's own
`finally`. This is deliberately the *narrowest* bundle this lane's own
validators need, not B4's full schema (durable evidence root resolved
before scratch substitution, repo sha, rubric hash, file inventory with
sha256s, …) — the field names (`run_id`/`harness`/`actor`/`outcome`) are
chosen to be CLOSE to a subset of B4's described schema, but B4's landed
writer names the corresponding fields `actor_backend`/`actor_model`/nested
`counts` rather than this module's flat `actor`/`outcome`/`turn_count`, so
migrating callers to B4's real writer is a small field-mapping change, not
a pure rename — see "Coverage inventory" below for the exact mapping and
its owner.

### Coverage inventory

Council D-19: a matrix, **never one green check per harness** — this table
therefore reports two DIFFERENT things per cell, because "a gated test
file exists for this harness" and "this harness has a recorded clean live
run" are not the same claim, and conflating them is exactly what D-19
forbids. As of this writing, **every** CLI/tmux cell's live-run count is
`0/O-6` (O-6: the owner's required number of independent clean runs,
astra proposed 3) — the CLI/tmux path's two structural blockers (a scratch
tmux socket path past AF_UNIX's `sun_path` limit, and a `TmuxHarness` that
addressed the wrong tmux server) are now fixed and mechanically verified
(`tests/test_acceptance_isolation.py`, `tests/test_harness_matrix_live_mechanics.py`),
but no live run against a real harness binary has been executed under this
fix. Updating the live-run count is a follow-up action on the owner's
machine, not a claim this document makes in advance of it.

| Feature | web (ACP): test exists (gated) | web (ACP): recorded clean live run | CLI/tmux: test exists (gated) | CLI/tmux: recorded clean live run |
| --- | --- | --- | --- | --- |
| kiro | ✅ `test_kiro_web_acp_lane.py` (mechanical validators) | 0/O-6 | ✅ `test_harness_matrix_live.py` (mechanical validators; verified auth probe) | 0/O-6 |
| codex | — (not a web-ACP surface) | n/a | ✅ `test_harness_matrix_live.py` (mechanical validators; presence-only probe) | 0/O-6 |
| claude | — (not a web-ACP surface) | n/a | ✅ `test_harness_matrix_live.py` (mechanical validators; presence-only probe) | 0/O-6 |
| pi | — | n/a | ✅ `test_harness_matrix_live.py` (mechanical validators; presence-only probe) | 1/O-6 real-auth (`receipts/harness-evidence-2026-09-16`) |
| opencode (PREVIEW) | — | n/a | ✅ `test_harness_matrix_live.py` (mechanical validators; presence-only probe) | 1 mechanical pass, no model reply (provider limit; see receipt) |
| grok (PREVIEW) | — | n/a | ✅ `test_harness_matrix_live.py` (mechanical validators; presence-only probe) | 1/O-6 real-auth (`receipts/harness-evidence-2026-09-16`) |

Tracked exclusions (named here, not silently absent, each with the lane
that owns closing it):

- **D-21(1) "install + doctor + launch green"**: only *launch* is driven
  by this lane. `studyloop install` has real side effects (installs uv
  tools / agent definition files onto the machine running the test) and is
  deliberately NOT invoked by an automated acceptance run; `studyloop
  doctor`'s read-only checks are not yet wired in either. **Owner: this
  lane (B2)**, a follow-up, not B4's.
- **D-21(3) "lexical `session_search` hits a prior turn id"** and
  **DB-row-level validators generally** (topic/struggle rows,
  `session_search` id-set membership, a written wind-down record) are not
  implemented in either lane above. That schema belongs to the
  session-memory subsystem. **Owner: B4.**
- **D-21(4) "export writes a valid session artefact"**: no export step
  exists in either lane. The closest existing CLI surface
  (`studyloop brain publish`) writes to a configurable second-brain
  destination, not a lexical "session artefact", and wiring it in was
  judged too broad a scope-add for a fix round with no live run to verify
  it against. **Owner: B4** (the evidence-writer/session-artefact schema
  this depends on is already B4's).
- **D-21(6) "persona/mode header correct"**: only `mode == "ended"` is
  asserted. The mentor's *persona* is not recorded anywhere in
  `session-state.json` (only `mode`, `topic`, `energy`, …) — verifying it
  would mean asserting on pane text, which D-17 forbids as an assertion
  target. **Owner: B4** (a DB-row-level persona-hash validator, per
  `history.sessions.update_persona_hash`, is the right shape once B4's
  validators land).
- **Per-harness authenticated-availability probes**: only `kiro` has one.
  The other five harnesses fall back to binary-presence-only, so a present
  but unauthenticated binary surfaces as a live-run **failure** (budget
  cutoff via `TurnBudgetExceededError`), not a named skip, until each gets
  its own probe. **Owner: this lane (B2)**, a follow-up.
- **The durable evidence root**: `tests/acceptance/evidence.py` (B2's
  minimal writer) still writes under whatever root its caller passes (the
  test's own `tmp_path`), not the durable, pre-scratch-substitution root.
  B4's full schema (`tests/acceptance/uat/bundle.py`: `resolve_durable_root`,
  the manifest schema, sha256 file inventory) now EXISTS and is unit-tested
  (`test_uat_bundle_writer.py`), but swapping `evidence.py`'s callers over to
  it is still a follow-up — the two schemas share a handful of field names
  by design (`run_id`, `harness`), but `evidence.py`'s `actor`/`outcome`/
  `turn_count` and `bundle.py`'s `actor_backend`/`actor_model`/nested
  `counts` diverge in both name and shape, so this is a small field-mapping
  change, not a pure rename. **Owner: B4** (schema delivered; integration
  into the harness-matrix lane's evidence calls, including that mapping,
  pending).
- **`grok`-over-ACP**: an optional follow-up per this lane's own council
  amendment, never a blocker on the CORE three or the other two PREVIEW
  harnesses. **Owner: this lane (B2)**, optional.

## The UAT (sign-off) tier

UAT is the extended sign-off tier the owner described verbatim: browser
journeys through the real web UI with Playwright traces + screenshots,
pedagogy graded against a WRITTEN, VERSIONED rubric by a council of
models with the coordinator as final arbitrator, and a complete evidence
bundle recorded OUTSIDE the user's public data/directory/docs.

It gets its OWN opt-in on top of acceptance (council D-13):
`STUDYLOOP_UAT=1`, required IN ADDITION to `STUDYLOOP_ACC=1` — set both,
or invoke `just testuat`, which sets both for you. Every test under
`tests/acceptance/uat/` lives behind this second gate, enforced by that
subpackage's own `conftest.py`, and a plain `just testacc` (or the bare
`acceptance` marker) never collects it — see `--ignore=.../acceptance/uat`
on the `testacc` recipe above.

### What ships in this lane

| Module | Job |
| --- | --- |
| `tests/acceptance/uat/bundle.py` | The full evidence-bundle writer: `manifest.json` (run id, date, repo sha + dirty/patch identity, harness+version, platform, auth mode, actor backend+model, rubric version+hash, seeds, full pass/fail/skip counts, failure artefacts, a sha256 file inventory), a path-escape guard, and `resolve_durable_root` — the durable evidence root resolved from an explicitly-passed "real" environment, never from a live `STUDYLOOP_STATE_DIR` (council D-14). The run dir it creates is private (`0o700`) and every write — named files and `manifest.json` — is atomic (temp file + `os.replace`); see "The durable evidence root: privacy, atomicity, retention" below for the full D-14 breakdown including retention policy. |
| `tests/acceptance/uat/redaction.py` | The versioned, hash-pinned redaction rule list (`data/redaction_rules_v1.yaml` + `data/redaction_registry.json`) and the redacted-summary generator `releases/` may ingest — allowlisted structured fields only, with every field's VALUE also scanned for a leaked home path or key-shaped token before it is trusted as clean. |
| `tests/acceptance/uat/rubric.py` | The versioned, hash-pinned sign-off rubric loader (`data/rubric_v1.md`, markdown+YAML frontmatter): criteria, scale anchors, cited evidence per criterion, and an explicit `reject_if` list. |
| `tests/acceptance/uat/strict_runner.py` | The strict sign-off semantics (council D-13): zero cells selected is a FAIL, any REQUIRED cell recorded as skipped (or simply missing) is a FAIL — a sign-off can never pass through skips. |
| `tests/acceptance/uat/test_journey_smoke.py` | A CI-safe mechanics smoke test: the hermetic server (E-B2) + a scripted turn sequence + the bundle writer, composed end to end, with the mentor played by the repo's existing ACP stub (`tests/_stub_acp_agent.py`) — no real harness binary, no LLM, no network. |
| `tests/acceptance/uat/test_plan_journeys.py` | The three study-plan doors as required sign-off cells under the strict runner, against one hermetic world shared by every process: `architect_launch` (the real Plans view's **Plan with architect** in a real browser → one planning-purpose start → the labelled console, the label surviving a reload, the brief's structure in the persona the stub agent received, no plan created), `mcp_lifecycle` (the real `studyloop-mcp` server over stdio, the nine tools listed, create → activate → record a checkpoint → set a milestone → history, then the same plan read back through the web server) and `now_with_active_plan` (the Today card's "Advances plan" line and `/api/now`'s `plan_refs` naming the plan). Writes the full bundle to the durable root plus a redacted summary; grades no rubric (a stub agent holds no conversation) and says so in its arbitration note. |

### Hash-pinning, the same shape twice

Both the redaction rules and the rubric are versioned markdown/YAML
documents whose `version` field is pinned, in a small sibling
`*_registry.json`, to that exact file's sha256. Editing either file in
place — changing its content without bumping `version` and registering a
new hash — is rejected by the loader (`RedactionRulesTamperedError` /
`RubricTamperedError`), never silently accepted. This is "never gate at
the point estimate": the rubric version + hash a run graded against enters
that run's manifest BEFORE grading starts, so a run can never be graded
against a rubric that was edited mid-grading.

### The durable evidence root: privacy, atomicity, retention (D-14)

The brief names three properties for the durable evidence root beyond
"resolved from the pre-substitution environment" (already covered above):

- **Created private.** `write_bundle` creates (or, for a pre-existing
  directory, tightens) the run directory to `0o700` regardless of the
  process umask — a shared box or CI runner with a permissive umask (e.g.
  `022`) must never leave a bundle world- or group-readable, since it can
  carry real learner transcripts and message bodies before redaction runs.
- **Exported atomically.** Every file `write_bundle` writes, including
  `manifest.json` itself, goes through a temp-file-then-`os.replace` in the
  same directory as its final path. A crash between the temp write and the
  rename can never leave a half-written artefact observable at its final
  name — the destination is either the complete old content (if any) or
  the complete new content, never a partial one.
- **Retention.** UAT evidence bundles are NOT swept automatically — that is
  the entire point of resolving a durable root outside the acceptance
  tier's per-test scratch `STUDYLOOP_STATE_DIR` sweeper (D-14). Bundles
  accumulate under `~/.local/share/studyloop/uat/<run-id>/` (or
  `STUDYLOOP_UAT_EVIDENCE_ROOT`) until a human prunes them; there is no
  code-enforced expiry. Recommended practice: keep a private bundle only
  as long as its run may need re-inspection (a rule of thumb is 90 days),
  then delete the run directory — the REDACTED summary this bundle
  produced into `releases/` (see `releases/uat-signoff-template.md`) is
  the durable, shareable record that outlives it. This is a documentation
  and operator-discipline control, not an automated one; a future lane may
  add a `studyloop uat prune --older-than` command, but none exists yet.

### Mechanism tests are UNGATED (council D-19/D-26)

Every module above has an ungated unit-test twin living directly under
`tests/` — `test_uat_bundle_writer.py`, `test_uat_redaction.py`,
`test_uat_rubric_loader.py`, `test_uat_strict_runner.py` — carrying no
`acceptance` marker, so they run in every `just test`/CI invocation. Only
the live-ish `test_journey_smoke.py` lives inside the gated
`tests/acceptance/uat/` tree, matching the same "a drift guard gated
behind an opt-in nobody sets in CI never actually guards anything"
principle `test_harness_matrix_live_mechanics.py` already established for
the harness matrix.

### What this lane deliberately left out

The brief's full scope is considerably larger than what a single fix
round can land test-first. Named here, not silently absent:

- **The real UAT journeys** (session start → study conversation with an
  LLM learner → topic/struggle logging → wind-down → resume → review,
  plus embedding/hybrid-retrieval checks and fault journeys) are not
  implemented. `test_journey_smoke.py` proves the MECHANICS three
  pieces above compose; it is not a sign-off run, grades no rubric, and
  uses a scripted stub mentor rather than a real coding harness. The
  study-plan journeys in `test_plan_journeys.py` are a real strict
  sign-off over three cells, but with the same stub agent: they prove the
  product surfaces (browser, stdio MCP, the now engine) and the shared
  store, not an architect's interview.
- **Council grading** (each seat receiving a bundle summary + rubric and
  returning cited per-criterion scores, hash-pinned seat identities, an
  `ARBITRATION` file) is not implemented — the rubric loader and
  redaction generator this depends on exist; the grading procedure and
  the arbitration workflow around them do not yet.
- **The sign-off definition as a released, checkable contract** (which
  journeys must pass + the rubric floor + the no-skipped-required-cells
  rule, wired into the release process) is not written — `strict_runner.py`
  provides the semantics a future sign-off definition would call.
- **Wiring `bundle.py` into the existing harness-matrix acceptance lane's
  evidence calls** (`tests/acceptance/evidence.py`) is not done — see
  "Coverage inventory" above.
- **`releases/uat-signoff-template.md`** documents the redacted-summary
  shape a real sign-off run's release note would carry; no real run has
  produced one yet.

## Rules that keep the tier honest

- **Missing binary or credential → named skip.** The reason states which
  binary (`kiro-cli`) or which environment variable is missing. Nobody
  should have to read the test body to find out why a run went green with
  nothing exercised.
- **Unknown selection value → loud failure.** `STUDYLOOP_ACC_HARNESS=oclode`
  fails the collection, naming the bad value and the known set.
- **The gate itself is tested without opting in**, via a subprocess that
  *explicitly* selects `-m acceptance` — a plain, deselecting `pytest` run
  reports nothing about a marker it never collected, so verifying the skip
  reason needs a run that asks for it on purpose. See
  `tests/test_acceptance_gate.py`.
- **A failed sweep guard is never silently swallowed.** It is a test failure
  that leaves the scratch tree on disk for inspection.
- **`just testacc`'s arguments are positional.** See "Running it" above —
  this is the one place in this document worth re-reading if a run behaves
  as though an argument was never passed.
