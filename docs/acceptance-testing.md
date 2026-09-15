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
| UAT (sign-off) | `STUDYLOOP_UAT=1` under `tests/acceptance/uat/` | Browser journeys + pedagogy graded against a written rubric, for a release sign-off | Its own opt-in on top of acceptance; a later lane |

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
| `LITELLM_API_KEY` | `ACTOR=gateway`: the key for your LiteLLM proxy | unset → `gateway` skips, naming it |
| `LITELLM_BASE_URL` | `ACTOR=gateway`: your proxy's address | unset → `http://127.0.0.1:4000` |
| `STUDYLOOP_ACC_GATEWAY_MODEL` | `ACTOR=gateway`: which alias behind the proxy plays the learner | unset → `gateway` skips, naming it |
| `STUDYLOOP_ACC_DIRECT_PROVIDER` | `ACTOR=direct`: a `provider_profiles` slug (`openai`, `openrouter`, `gemini`, `anthropic`) | unset → `openai` |
| `STUDYLOOP_ACC_DIRECT_MODEL` | `ACTOR=direct`: a curated model id within that provider | unset → the provider's cheapest curated model |
| `STUDYLOOP_ACC_HARNESS_ACTOR_CMD` | `ACTOR=harness`: the command that launches the second harness | unset → `harness` skips, naming it |
| `STUDYLOOP_UAT` | The UAT tier's own, additional opt-in (a later lane) | unset (tier is off) |

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

The CLI/tmux path (all six harnesses, not just Kiro-over-web) is a later
lane's job, tracked as the harness × surface × transport coverage matrix.
This lane's validators are mechanical (a real session started, real turns
were answered, the session ended without a crash) rather than DB-row-level
(topic/struggle rows, `session_search` id-set membership, a written
wind-down record) — those validators depend on the session-memory schema a
later lane wires into the acceptance tier's evidence writer.

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
