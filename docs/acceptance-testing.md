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
| **Acceptance** | `just testacc` | A **real** harness through the real product surface, real DB/session artefacts, a deterministic scripted learner | `STUDYLOOP_ACC=1`; the harness's real binary; opt-in, never runs in CI |
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
| `STUDYLOOP_ACC_ACTOR` | Which learner backend drives the conversation | unset → `scripted` |
| `STUDYLOOP_UAT` | The UAT tier's own, additional opt-in (a later lane) | unset (tier is off) |

An unknown value in `STUDYLOOP_ACC_HARNESS` or `STUDYLOOP_ACC_ACTOR` **fails
the run**, naming the bad value and the known set — it is a typo you made,
not something to skip past quietly.

`STUDYLOOP_ACC_ACTOR` currently supports only `scripted` — a deterministic,
versioned turn script with no LLM on the learner side (see "The scripted
actor" below). `gateway` (LiteLLM), `direct` (a plain provider SDK) and
`harness` (a second harness plays the learner) are a later lane's job; the
env var's shape is reserved now so this lane's tests already assert against
the final contract.

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

The recipe sets `STUDYLOOP_ACC=1` for you; it is the one place you don't set
that variable by hand. Under the hood it is:

```bash
STUDYLOOP_ACC=1 STUDYLOOP_ACC_HARNESS="<harness>" STUDYLOOP_ACC_ACTOR="<actor>" \
    uv run --group dev pytest -m acceptance <tests>
```

Without `STUDYLOOP_ACC=1`, `just test` (and CI) never see these tests at
all — the `acceptance` marker is deselected by default in **both**
`pyproject.toml` files, the same pattern already used for `integration`,
`e2e` and every `live_*` marker.

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
  from `HOME`, still lands under the scratch tree.

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

## The scripted actor

`ACTOR=scripted` drives the **mentor** through an ordered, versioned turn
script rather than a live LLM on the learner side (`tests/acceptance/turn_script.py`).
A turn script is plain data:

```json
{
  "version": 1,
  "turns": [
    {"prompt": "In one sentence, what is a Python decorator?"},
    {
      "prompt": "And a closure?",
      "expect_contains": ["closure"],
      "expect_not_contains": ["I don't know"]
    }
  ]
}
```

The loader is strict: an unknown top-level or per-turn field is a loud
`TurnScriptError`, not a silently-ignored key, and the format is versioned so
a future incompatible shape is rejected by name rather than misread.

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
