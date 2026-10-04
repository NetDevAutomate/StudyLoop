# Optional topic modules: proposal and contribution boundaries

**Design proposal, not a shipped plugin API or registry.** This page describes a direction for
discussion, motivated by [issue #53: Kubernetes drills](https://github.com/NetDevAutomate/StudyLoop/issues/53).
It is not approval of that implementation or a promise that third-party code is safe to install.
The repository does not currently provide the module lifecycle described below.

## The goal: specific practice, topic-agnostic foundations

StudyLoop should support learning Kubernetes without becoming a Kubernetes application. A topic module
could supply drills, prerequisite checks, verification and teaching material while the core continues
to own sessions, accessibility, consent, learner records and mentor interaction. A learner who does not
install the module should not need its tools or see its setup errors.

Start with a small optional practice workflow. Do not start by creating a general plugin platform,
a separate PTY stack, or a Kubernetes-specific branch through planning and recall. A second independent
topic should exercise the proposed boundary before it is declared a stable extension API.

## What exists today, and what needs design

| Existing capability | Boundary to preserve | Not yet provided by that capability |
| --- | --- | --- |
| JSON practice decks, `content/schemas.py` | Validate input; retain learner-facing success criteria | An arbitrary YAML drill format or module installer |
| `verification.kind: command` | Explicit execution plus approval of the exact command; reload-and-compare protection | Blanket per-deck permission for repeated background checks |
| `verification.setupCommand` | Metadata is surfaced in verification results | Automatic setup or teardown execution |
| Web session/terminal transport | Reuse session ownership and existing WebSocket protections | A general-purpose untrusted-code sandbox |
| Mentor and learning records | Preserve evidence provenance and consent | Every successful shell command becoming proof of mastery |

The JSON field name is `setupCommand`; the Python attribute is `setup_command`. This is
not an automatically executed setup hook. Read `content/schemas.py`, `learning/practice.py`,
`cli/_practice.py` and `test_practice_verify.py` before
proposing an adapter. A CLI verification path does not by itself mean that a new browser practice mode
or a command-execution endpoint already exists.

## Suggested first slice for Kubernetes drills

Discuss placement under a generic Practice or Labs entry before introducing a new top-level mode.
The first prototype should offer one synthetic drill, an explicit **Check progress** action and a
clear explanation of what will run. Reuse the existing terminal/session path where its contract fits;
propose any missing generic seam instead of maintaining a parallel browser terminal.

Keep Docker and kind optional external prerequisites. A diagnostic may report their availability,
versions and relevant connection failures without creating a cluster or changing context. Installing
Python extras does not install Docker, and a diagnostic should not silently download tools or create
resources. Cluster setup and cleanup are separately consented actions.

Use a dedicated disposable cluster and explicit context, not the learner's current kubeconfig context.
Bind every check to that identity. Delete only resources created and owned by the drill. Docker daemon
access is powerful, and a kind cluster is not a host sandbox; document these limits before execution.

## Why “read-only” needs more than a label

A script can claim to be read-only and still execute arbitrary shell code, disclose Secrets, read host
files or contact a network endpoint. Neither a YAML field nor an LLM's judgement establishes safety.
Keep the existing per-command consent path for the first slice.

Repeated automatic checks require a separate, reviewed permission model. A possible future grant would
be attempt-scoped and tied to the module version/content digest, exact commands, working directory,
cluster identity, permitted data and expiry. It must be revocable; changed content or an update must
invalidate approval. Setup, checks and destructive cleanup need separate capabilities. Enforce allowed
operations through the runner and least-privilege credentials; do not infer safety from a command-name
allowlist alone. A denied grant must have no execution or recording side effects.

Do not infer command completion merely from a terminal prompt or screen text. Automatic coaching needs
a reliable completion signal, cancellation and bounded concurrency. Initially, manual checks avoid
that ambiguity. Keep transient probes separate from durable learning outcomes so repeated checks do
not flood the learner's history. Passing a check establishes the observed task result, not conceptual
understanding; a teach-back can provide different evidence.

Command history and terminal output can contain credentials. Minimize collection to an active attempt,
explain retention, redact before persistence, and never claim redaction catches every secret. Keep
captured learner data out of public drill definitions, screenshots and the proposed registry.

## A registry, in stages

A GitHub catalogue is a useful possible destination, but discovery, installation and trust are
different responsibilities. Catalogue inclusion should never silently authorize execution.

1. **Agree the contract and prove a vertical slice.** One optional drill, manual verification,
   existing session authority, deterministic tests and a documented live disposable-cluster check.
2. **Prove the boundary with another topic.** Identify what genuinely varies: content, prerequisites,
   runner and evidence. Keep topic names and runtime dependencies out of the core workflow.
3. **Publish a versioned manifest contract and catalogue.** Define compatibility, validation, review
   and ownership before adding installation. An initial catalogue can be a reviewed list, not a loader.
4. **Consider explicit installation and lifecycle support.** Pin immutable artifacts and verify hashes;
   preview capabilities before consent; define updates, revocation, uninstall and learner-data retention.
   Never import arbitrary repository code automatically during application startup or discovery.

A future manifest needs, at minimum: stable module ID, schema version, module version, supported
StudyLoop contract range, source and immutable artifact digest, license, maintainer/contact,
prerequisites, declared capabilities, entry points/content locations and documentation. These are
design requirements, **not accepted fields in a current StudyLoop configuration file**. Do not add a
made-up `modules:` section to your local config expecting it to work.

Before hosting a registry, agree who reviews entries, how security reports and abandoned modules are
handled, how unsafe versions are revoked, and what compatibility testing inclusion requires. A signed
or hashed artifact establishes identity/integrity, not harmlessness. No core dependency should require
network access to that registry on startup.

## Small-PR plan and definition of done

| Slice | Reviewable outcome | Required evidence |
| --- | --- | --- |
| Design | Issue answers, scope, permission model and OpenSpec proposal; ADR if appropriate | Existing interfaces inspected; public limitations stated; no claim of a shipped registry |
| Deterministic core/adapter slice | One validated drill and manual check behind a narrow boundary | Valid/invalid input, refusal, changed-content approval, timeout/cancel, cleanup and no-execution tests |
| Optional UI slice | Accessible learner flow using existing session authority | Isolated Playwright journey, failure/retry, keyboard/focus, reload, module disabled and missing prerequisites |
| Live proof | One disposable kind workflow, opt-in only | Explicit target identity, setup/check/cleanup evidence, no default-context access and only owned resources removed |

The first useful slice is done when a new contributor can follow the guide from a clean supported
environment, run one drill, consent to one check, see its result, cancel safely and remove only its
resources. Default tests must work without Docker, kind, cloud credentials or a paid model. Core study
flows must still work when the module is absent. Record remaining limitations; do not rename them
“production ready” because the happy path worked once.

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

See the [testing cookbook](contributor-testing.md) for working test patterns and the
[contributor guide](contributing.md) for the review process. Discuss the contract before promising
a registry or writing a broad loader: keeping the core small is part of making contributions sustainable.
