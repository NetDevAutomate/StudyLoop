# Council brief — review of "StudyLoop Modules — contract v1 (MVP proposal)"

Date: 2026-10-04. Coordinator: Kiro (Claude lineage), who also drafted the proposal — so the
reviewers are deliberately other model families, and the coordinator's own preferences are
not evidence.

## What you are reviewing

`openspec/changes/module-contract-v1/proposal.md` in this repository. Read it in full first.
It is a **design proposal**, not an implementation: nothing in it exists unless a line is
marked **Exists**. It will be shared with two prospective contributors (a Kubernetes
practitioner who wrote the first candidate module, "kdrill", and a developer new to the
codebase) to get their views; the owner wants to know what is wrong with it *before* they read it.

## Who the deliverable is for, and what "ready" means

The owner is a solo maintainer of a pre-1.0, public, AuDHD-aware Socratic study tool who wants
colleagues to be able to contribute and maintain technology-specific practice modules
**without** each one becoming a bespoke core change he has to review. "Ready" means: a
contributor can build a module from the contract alone, a core reviewer can check it in
minutes with a tool, and the core stays topic-agnostic.

## Hard constraints — settled by the owner, NOT up for review

Spend no budget re-litigating these; do flag if the proposal *violates* one.

- C1. **Socratic rule.** The mentor never gives direct answers; hints/solutions reach the learner
  only through the mentor. Modules cannot bypass this.
- C2. **AuDHD design rules.** Max three active topics; one generic menu entry, not one per
  technology; no overdue counters or shaming; tangents are parked, not corrected; a learner
  who has not installed a module never sees its errors.
- C3. **Consent is per exact command in v1** (R-15: show the resolved command, confirm, re-read
  and compare before executing — R-15b). No standing grants in v1.
- C4. **Rule of three.** The contract is not declared stable until a second, unrelated module
  fits it. No registry/index repository exists before that.
- C5. **Harness is the LLM.** Users reach the mentor through their own coding-agent
  subscription (Kiro CLI, Codex, Claude Code, pi, OpenCode, Grok Build). Nothing may assume an
  API key.
- C6. **Offline by default.** Default tests and `module check` run with no Docker, kind, cloud
  credentials or paid model.

## Invariants that make a naive plan wrong at runtime

- I1. Content schemas are Pydantic with `extra: forbid` (`packages/studyloop/src/studyloop/content/schemas.py`).
  Any new field is a schema change in core; the proposal's example deck fails validation today.
- I2. There is **one** live study session, claimed through a cross-process state file
  (ADR-0009, `docs/adr/0009-one-session-authority.md`). A "drill" is not a second session.
- I3. The web UI has **no command-execution endpoint today**. `practice verify` with R-15 exists
  only in the CLI (`learning/practice.py`, `cli/_practice.py`). The proposal's "Check progress"
  button would be a new, security-critical surface.
- I4. The web UI runs over plain HTTP on the LAN (`--lan`, Basic auth) for tablet use; anything
  that executes commands must respect existing origin checks (`web/ws_origin.py`).
- I5. The mentor is a separate agent process in a PTY/ACP session; how a check result would be
  delivered *to* the mentor has **not** been verified by the coordinator. Treat it as unknown.
- I6. Core must never import module code (the proposal's MC012). Drill commands are the only
  executable content, and only via core's runner.

## Known weak points the coordinator already sees (numbered, so you can reference them)

- W1. I5 above — no verified channel from runner result to mentor.
- W2. I3 above — the web consent + execution endpoint is unbuilt and under-specified in §5.5.
- W3. Minting a view-only kubeconfig (ServiceAccount + `view` binding + token) is 4–6 hours of
  Kubernetes plumbing only testable live; the coordinator has proposed moving it to v2.
- W4. `module add <git-url@sha>` pinning is proposed for v1; the coordinator has proposed
  local-path-only in v1.
- W5. kdrill's "Auto Coach runs a check after every command" is deferred to v2 wholesale; the
  proposal does not say what the learner experiences in v1 instead, beyond a button.
- W6. Effort estimate given to the owner: 45–60 agent-hours as written; 35–45 with W3+W4 cuts.

## Explicitly out of scope — do not plan work here

Hosting a registry; Web UI installation; standing/attempt-scoped grants; modules shipping
importable code; browser-based drill authoring; target kinds beyond `workdir` and
`kubeconfig-context`.

## Questions — answer every one, countably, in this order

- Q1. The **three** changes that would most improve the proposal, ranked, each naming the
  section it changes and the sentence to replace or add.
- Q2. Of the proposal's nine reviewer questions (§10), which have a **wrong recommended
  answer**? List by number with one reason each; "none" is a valid answer.
- Q3. The two scope cuts (W3 view-only → v2; W4 local-path-only add): **accept or reject each**,
  one reason each.
- Q4. Security holes in the §5.5 runner contract under C3 and I6 — a numbered list, each with
  the attack in one sentence and the fix in one sentence. Say "none found" if so.
- Q5. Up to **three** missing conformance rules (MC013+), each as `MCnnn — <one-line check>`.
- Q6. Would a SQL lab on in-process DuckDB fit this contract **without changes**? Answer yes/no
  and name the first field or runner behaviour it would need that is missing.
- Q7. Is W6 credible? Give **your** number in agent-hours and the one DoD item you would move
  most.
- Q8. **Where will the other reviewers be wrong?** Name the recommendation you expect at least
  one other model to make that you reject, and why.
- Q9. **What does this brief or the proposal get wrong?** Contradictions between sections,
  constraints that conflict, claims you could not verify in the code (cite the file).

## Rules for the review

- Verify claims against the code before planning around them. Files worth checking:
  `packages/studyloop/src/studyloop/content/schemas.py`, `learning/practice.py`,
  `cli/_practice.py`, `web/routes/session/_start.py`, `web/routes/session/_options.py`,
  `web/ws_origin.py`, `doctor/*.py`, `docs/adr/0009-one-session-authority.md`,
  `packages/studyloop/tests/test_practice_verify.py`. Cite `path:line` for any code fact.
- Do **not** modify any existing file, do **not** run writing git commands, keep reads inside
  this repository. The one permitted write is your own result file (named in your task).
- Another model family is answering this same brief separately and a coordinator will
  arbitrate. **Do not hedge toward consensus**; a clear wrong answer is more useful than a
  vague safe one.
- Budget: 900–1200 words. Use the headings `Q1` … `Q9` exactly, then a final line
  `Verdict: adopt as-is | adopt with changes | rework` with one sentence of rationale.
