---
version: 1
criteria:
  - id: accuracy
    prompt: "Did the mentor's answers stay factually correct for the topic taught?"
    scale: [1, 2, 3, 4, 5]
    anchors:
      1: "Confidently wrong on a core fact."
      3: "Mostly correct, one uncited or shaky claim."
      5: "Every claim correct and, where relevant, sourced from the lesson."
    evidence:
      - transcript.jsonl
      - retrieval_receipts.jsonl
  - id: pedagogy
    prompt: "Did the mentor teach (explain, check understanding, adapt) rather than just answer?"
    scale: [1, 2, 3, 4, 5]
    anchors:
      1: "Pure answer-dump, no checking or adaptation."
      3: "Some Socratic questioning, inconsistent follow-through."
      5: "Consistently checks understanding and adapts to the learner's answers."
    evidence:
      - transcript.jsonl
  - id: session_lifecycle
    prompt: "Did session start / wind-down / resume behave as documented?"
    scale: [1, 2, 3, 4, 5]
    anchors:
      1: "A lifecycle step failed or produced no evidence."
      3: "Lifecycle completed but with a rough edge (e.g. slow resume)."
      5: "Every documented lifecycle step completed cleanly, evidenced."
    evidence:
      - manifest.json
      - traces/
reject_if:
  - "accuracy scores 1 (confidently wrong) on any criterion evidence item"
  - "a REQUIRED journey cell is skipped rather than run (D-13: a sign-off can never pass through skips)"
  - "the evidence bundle is missing manifest.json or any file its own inventory names"
  - "semantic participation was required by the journey but retrieval_status.semantic never fired (astra QB3)"
---

# UAT sign-off rubric, version 1

This rubric is loaded by `tests/acceptance/uat/rubric.py`, which verifies
its sha256 against the pinned hash in `rubric_registry.json` for the
`version` declared above -- an edit made in place, without bumping
`version` and registering a new hash, is rejected as tampering
(`RubricTamperedError`), never silently accepted.

## How a council seat grades

Each seat receives the bundle's REDACTED summary (never the raw private
bundle) plus this rubric, and returns one score per criterion above, with
a citation into the evidence the criterion names. The coordinator
arbitrates all seats' scores into a single `ARBITRATION` file stored
alongside the private bundle, never inside `releases/`.

## Reject-if conditions

The `reject_if` list above is the CHECKABLE failure-condition contract:
any one of these being true makes the run a FAIL, independent of what the
weighted per-criterion average would otherwise say ("never gate at the
point estimate" -- a run that scores well on average but trips a
reject-if condition still fails).

## Pre-registration

This rubric's `version` and content hash enter a run's `manifest.json`
BEFORE grading starts -- never appended after the fact -- so a run cannot
be graded against a rubric edited mid-grading.
