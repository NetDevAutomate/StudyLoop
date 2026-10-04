# Optional topic modules: proposal and contribution boundaries
<!-- facts: F11 -->

**Design proposal, not a shipped plugin API or registry.** This page summarises the module contract
proposed in [`openspec/changes/module-contract-v1/proposal.md`](https://github.com/NetDevAutomate/StudyLoop/blob/main/openspec/changes/module-contract-v1/proposal.md)
(revised after a four-model council review on 2026-10-04) and the boundaries a contribution must respect,
motivated by [issue #53: Kubernetes drills](https://github.com/NetDevAutomate/StudyLoop/issues/53). It is
not approval of that implementation or a promise that third-party code is safe to install; the repository
does not provide the module lifecycle described below, and the proposed index has its own page,
[Module Index (Proposal)](contributor-module-index.md).

## The goal: specific practice, topic-agnostic foundations

StudyLoop should support learning Kubernetes without becoming a Kubernetes application. **Modules
declare; core executes**: a module is a directory of *data* that core validates and runs through its
own session, consent and verification machinery, while core keeps sessions, accessibility, consent,
learner records and mentor interaction. A learner who has not installed a module never sees its
prerequisites, its setup errors or its menu entry.

Start with a small optional practice workflow, not a general plugin platform, a separate PTY stack or
a Kubernetes-specific branch through planning and recall. A second independent topic must exercise the
proposed boundary before it is declared a stable extension API.

## The proposed contract in one table

Everything in this table is proposed, not built, and the proposal is the authority where they differ.

| Proposed element | What the council-amended proposal says |
| --- | --- |
| Module layout | `module.yaml` manifest, `decks/*.json`, `mentor/brief.md`, optional `scripts/`, README with four required sections, LICENSE, CHANGELOG, own offline tests. No Python, no entry points, nothing core imports |
| One content format | Drills are StudyLoop's existing `PracticeDeck` JSON plus six additive fields (deck and task `id`, `solution`, `scaffolding`, `mentorNotes`, `verification.cleanupCommand`); kdrill's YAML converts to it, the format does not bend per tool |
| Prerequisites | An enum core owns (`docker`, `kind`, `kubectl` in v1); the probes live in core's `doctor/`, report only, never create resources |
| Runner | Each phase is one executable under `scripts/` plus literal arguments, run without a shell, in a clean environment, against a core-created disposable target; consent per phase, per execution, bound to the script's digest |
| The Labs entry | One generic Web UI entry, hidden until a module is installed, listing drills by module; in the MVP every check is triggered explicitly from the CLI |
| Browser checks | A **Check progress** button is v1.1, not the MVP: it needs an HTTP consent endpoint with same-origin, CSRF, one-use challenge and replay protection |
| View-only credential | Deferred to v2 **together with** the attempt-scoped grant that would let a check repeat without re-confirming; in v1 the disposable cluster is the boundary and per-phase consent the control |
| Conformance | A proposed `studyloop module check` command with quotable rule ids (MC001–MC016), run in the module repo's CI and later on every index entry |

## What exists today, and what needs design

| Existing capability | Boundary to preserve | Not yet provided by that capability |
| --- | --- | --- |
| JSON practice decks, `content/schemas.py` | Validate input; retain learner-facing success criteria | The six proposed fields, an arbitrary YAML drill format, or a module installer |
| `verification.kind: command` | Explicit execution plus approval of the exact command; reload-and-compare protection | Blanket per-deck permission for repeated background checks |
| `verification.setupCommand` | Metadata is surfaced in verification results | Automatic setup or teardown execution |
| Web session/terminal transport | Reuse session ownership and existing WebSocket protections | A general-purpose untrusted-code sandbox, or an HTTP consent endpoint |
| Mentor and learning records | Preserve evidence provenance and consent | Every successful shell command becoming proof of mastery |

The JSON field name is `setupCommand`; the Python attribute is `setup_command`. This is
not an automatically executed setup hook. Read `content/schemas.py`, `learning/practice.py`,
`cli/_practice.py` and `test_practice_verify.py` before proposing an adapter. The existing
`practice verify` path is reused for its consent protocol only: as built it runs the string through a
shell in the inherited environment and records a learner observation, which the proposed runner must
not inherit. A CLI verification path does not by itself mean that a new browser practice mode or a
command-execution endpoint already exists.

## Suggested first slice for Kubernetes drills

Place drills under the one generic Labs entry rather than a new top-level mode. The first prototype
offers one synthetic drill, a check the learner triggers explicitly from the CLI, and a clear
explanation of what will run; the browser **Check progress** button follows in v1.1. Reuse the existing
terminal/session path where its contract fits; propose a missing generic seam, not a parallel terminal.

Keep Docker and kind optional external prerequisites. A diagnostic may report their presence, versions
and connection failures without creating a cluster or changing context; installing Python extras does
not install Docker. Cluster setup and cleanup are separately consented actions.

Use a dedicated disposable cluster and explicit context, never the learner's own kubeconfig context;
`--context`, `--kubeconfig` and `kubectl config use-context` in a drill fail the proposed conformance
check. Delete only resources the drill created. Docker daemon access is powerful, and a kind cluster is
not a host sandbox; document these limits before execution.

## Why “read-only” needs more than a label

A script can claim to be read-only and still execute arbitrary shell code, disclose Secrets, read host
files or contact a network endpoint. Neither a YAML field nor an LLM's judgement establishes safety:
read-only is a capability the execution boundary grants, not a label. Keep per-command consent first.

Repeated automatic checks require a separate, reviewed permission model, and the proposal defers it to
v2 together with the view-only credential it depends on. Such a grant would be attempt-scoped and tied
to the module version and content digest, exact argv, target identity, permitted data and expiry; it
must be revocable, changed content must invalidate approval, and a denied grant must have no execution
or recording side effects. Setup, checks and destructive cleanup are separate capabilities.

Keep transient check results separate from durable learning outcomes: passing a check establishes the
observed task result, not understanding; a teach-back provides that evidence, and modules have no write
path to it. Command output can contain credentials: collect only for the active attempt, redact before
persistence, and never claim redaction catches every secret.

## An index, in stages

A reviewed index is a useful possible destination, but discovery, installation and trust are different
responsibilities. Catalogue inclusion should never silently authorize execution.

1. **Agree the contract and prove a vertical slice**: one drill, manual verification, existing session
   authority, deterministic tests and a documented live disposable-cluster check.
2. **Prove the boundary with another topic.** The council expects a SQL lab to need a new target kind;
   finding that out is the point of the stage.
3. **Publish the contract as stable and open an index repository** — a reviewed list with CI running the
   conformance check on every entry, not a loader or a hosted registry.
4. **Design installation and lifecycle only then**: pinned immutable artefacts, verified digests, updates,
   revocation, uninstall and learner-data retention. Never import repository code during startup or discovery.

What the index would and would not be, and what not to do today, is on
[Module Index (Proposal)](contributor-module-index.md); the manifest fields named there are design
requirements, **not accepted fields in a current StudyLoop configuration file**.

## Small-PR plan and definition of done

| Slice | Reviewable outcome | Required evidence |
| --- | --- | --- |
| Schema fields | The six proposed fields in core, shipped first and alone | Valid/invalid decks; existing decks still validate |
| Conformance and lockfile | The proposed check passes on scaffold output and fails on a fixture per rule; a lockfile written only after it passes | Fixture set covering every rule; refusal tests |
| Runner | One drill phase run as argv without a shell, per-phase consent, transient-only recording | Refusal, changed-content, timeout/cancel, cleanup and no-observation-written tests |
| Mentor delivery | A `practice_check` envelope reaches the mentor on both PTY and ACP transports | One integration test per transport |
| Labs UI | List, start, cancel under the one claimed session; no browser check | One isolated Playwright journey; module absent and prerequisites missing |
| Live proof | kdrill converted, passing the check, one live drill under `STUDYLOOP_LIVE=1` | Explicit target identity, setup/check/cleanup evidence, only owned resources removed |

The first useful slice is done when a new contributor can follow the guide from a clean supported
environment, run one drill, consent to one check, see its result, cancel safely and remove only its
resources. Default tests must work without Docker, kind, cloud credentials or a paid model, and core
study flows must still work when the module is absent. Record remaining limitations; do not rename
them “production ready” because the happy path worked once.

## Proposal template

```markdown
## Learner need and smallest workflow
Who benefits, and what can they do at the end?
Why an optional module rather than a core change?

## Existing boundaries reused
Content schema, session transport, verification, mentor and evidence paths:
Missing generic seam (if any):

## Permissions and lifecycle
Prerequisites and explicit target identity:
Setup / checks / cleanup capabilities:
Collected data, retention and redaction limits:
Consent, cancellation, timeout, update and uninstall behaviour:

## Proof and scope
Deterministic tests; browser journey; opt-in live test:
Behaviour when absent or disabled:
First small PR; later work explicitly deferred:
```

See the [testing cookbook](contributor-testing.md) for test patterns and
[Raising a pull request](contributor-pull-requests.md) for the review process. Discuss the contract
before promising an index or writing a broad loader: keeping the core small keeps contributions sustainable.
