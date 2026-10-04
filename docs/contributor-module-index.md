# Module Index (Proposal)
<!-- facts: F11 -->

The module index is at the **design stage**: nothing described on this page has been built, and no
command, file or configuration key named here exists in StudyLoop today. It is stage 3 of the
[module-contract proposal, §9](https://github.com/NetDevAutomate/StudyLoop/blob/main/openspec/changes/module-contract-v1/proposal.md#9-definition-of-done-ownership-order)
(`openspec/changes/module-contract-v1/proposal.md` in the repository), whose contract is summarised on
the [optional modules proposal page](contributor-modules.md).

## The goal

Topic-specific practice (Kubernetes drills, a SQL lab) without topic-specific dependencies in core.
A module would be a directory of data that core validates and runs through its own session, consent
and verification machinery; the index would be a reviewed list of such modules. StudyLoop should not
become a Kubernetes application, and the index should not become a loader.

## What exists today

1. JSON practice decks validated by `PracticeDeck` in
   `packages/studyloop/src/studyloop/content/schemas.py` (`extra: forbid`).
2. `verification.kind: command`, run only through `studyloop practice verify` with the exact command
   printed and confirmed first, and re-read before it runs so a changed command cannot ride an earlier
   approval (`packages/studyloop/src/studyloop/cli/_practice.py`).
3. Per-command consent: without confirmation the CLI prints *nothing executed* and stops.
4. `setupCommand` on a verification is metadata: it is surfaced in results, never executed.

## What does not exist

1. An installer, a lock file, or any command that adds, lists or removes a module.
2. An index, a catalogue repository, or any network fetch of one.
3. Automatic execution of setup, check or cleanup phases, or any check triggered from the browser.
4. A trust model: no signing, no review process, no revocation.
5. A stable manifest: the `module.yaml` shape is a draft open to change.

## The staged path, as proposed

1. Agree the contract and ship its schema fields, then prove one module end to end (kdrill, issue #53).
2. A second, unrelated topic (a SQL lab is the candidate) is built against the contract; the council
   expects it **not** to fit unchanged, and finding that out is the point.
3. Only then publish the contract as stable and open an index repository: a reviewed `index.json` of
   manifests pointing at sha-pinned artefacts, with CI running the conformance check on every entry.
4. Lifecycle (installation from a URL, updates, revocation, removal) is designed after the index, not before.

No stage has a date. Each one starts when the previous one has shipped its evidence.

## Proposed vocabulary

Every term here is *proposed*; none is accepted into a schema yet.

- **manifest** — `module.yaml`: id, `contract` version, module version, topic, licence, maintainers.
- **capabilities** — the phases a module may ask core to run (`terminal`, `setup`, `check`, `cleanup`);
  the runner would refuse anything undeclared.
- **prerequisites** — ids from an enum core owns (`docker`, `kind`, `kubectl` in v1); the probes live in
  core's `doctor/`, report only, and never create resources.
- **scaffolding levels** — `guided` / `hinted` / `unaided` / `exam`, kdrill's L0–L3 named for what the
  learner gets.

## Proposed safety invariants

1. **Modules declare; core executes.** A module ships no Python, no entry points, nothing core imports;
   each phase is one executable under the module's `scripts/` plus literal arguments, run without a shell
   in a clean environment, against a disposable target core created.
2. **The learner sees the prompt and the success criteria only.** `hint`, `solution` and the mentor brief
   reach the learner through the mentor, which asks before it tells.
3. **Consent is per phase, per execution**, bound to the script's content digest; a passing check records
   an observation on the attempt, never a learning record or a mastery claim.

## What a would-be author can do today

1. Open an issue describing the learner need and the smallest drill, using the template on the
   [optional modules proposal page](contributor-modules.md#proposal-template).
2. Convert your content to `PracticeDeck` JSON; it validates against the schema that exists now, and the
   six proposed fields are additive.
3. Read [issue #53](https://github.com/NetDevAutomate/StudyLoop/issues/53) and the proposal's
   §10 questions, and answer the ones that touch your topic.

## What not to do today

Do not add a `modules:` section to your `config.yaml` expecting it to work: no code reads it. The
settings loader ignores a key it does not look for, and the doctor's unknown-key check
(`unknown_top_level_keys` in `packages/studyloop/src/studyloop/settings.py`) reports it as inert. Do not
write a loader, a registry client, or a browser terminal for your topic; propose the missing generic
seam instead.

## When the first slice is done

The first slice is done when a new contributor, from a clean supported environment, can run one drill,
consent to one check, see its result, and cancel safely — with the default tests passing without Docker,
kind, cloud credentials or a paid model, and every core study flow unchanged when no module is present.

## Open questions and where they are decided

The proposal's §10 lists eleven questions, each with a recommended answer; they are decided on
[issue #53](https://github.com/NetDevAutomate/StudyLoop/issues/53) or as review comments on the pull
request that carries the proposal. The council review that amended the proposal is recorded in
`openspec/changes/module-contract-v1/council/2026-10-04-arbitration.md`. This page changes when they do.
