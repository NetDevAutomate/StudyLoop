---
version: 2
criteria:
  - id: labs_entry_discipline
    prompt: "Persona A (1, 2, 8): no Labs entry, no prerequisite text and no overdue counter before `module add`; exactly ONE Labs entry after it; none after `module remove`."
    scale: [1, 2, 3, 4, 5]
    anchors:
      1: "A Labs entry, counter or prerequisite text was visible with no module installed, or two entries appeared."
      3: "One entry, hidden correctly, but a stale list or hash resurrected it once."
      5: "Present only while the lockfile lists a module; one entry; nothing module-shaped anywhere else."
    evidence:
      - manifest.json
      - screenshots/
      - lockfile.diff
  - id: start_inside_one_session
    prompt: "Persona A (3, 6): starting a drill runs inside the single claimed session; a reload re-attaches to the SAME session; no second session or second console ever exists."
    scale: [1, 2, 3, 4, 5]
    anchors:
      1: "A second session was created, or the console cross-fired into another view."
      3: "One session, but the reload needed a manual reattach click."
      5: "One session id throughout; reload re-adopts it unaided; one console."
    evidence:
      - server-log.txt
      - session-state.json
      - screenshots/
  - id: keyboard_and_cancel
    prompt: "Persona A (4, 5): Tab / Shift-Tab traverse every Labs control with a visible focus ring; Escape (or Cancel) drops the drill with clear recovery copy and leaves the session where it was."
    scale: [1, 2, 3, 4, 5]
    anchors:
      1: "A control was unreachable by keyboard, or cancel ended or changed the session."
      3: "Traversal works but focus is not visible on one control, or the recovery copy needed a facilitator's gloss."
      5: "Every control reachable and visibly focused; cancel copy says what happened and what did not run."
    evidence:
      - screenshots/
      - console.json
  - id: nothing_mentor_side_nothing_executed
    prompt: "Persona A (throughout), §5.6 and §8: hint, solution and mentorNotes never appear in the DOM; no drill phase executes from the browser; a module declaring `kind` installs (conformance is static), `doctor` names the missing prerequisite and the module that needs it, and `drill` refuses before consent creating nothing (design.md §6 step 7, corrected 2026-10-05)."
    scale: [1, 2, 3, 4, 5]
    anchors:
      1: "Mentor-side text reached the page, or a phase ran without the CLI's typed consent."
      3: "Nothing leaked and nothing ran, but the prerequisite report was verbose or buried."
      5: "Only prompt and success criteria on the page; every phase ran from the CLI after `Run this phase now?`; the prerequisite report was one readable block."
    evidence:
      - page.html
      - cli-transcript.txt
      - labs-binding.json
  - id: mentor_delivery
    prompt: "A check result reaches the mentor pane as ONE labelled block (sentinels, `| `-prefixed tails) and the CLI says `Mentor told.`; when it cannot, the CLI names the reason."
    scale: [1, 2, 3, 4, 5]
    anchors:
      1: "The block never appeared, appeared twice, or the CLI stayed silent on failure."
      3: "Delivered, but the learner had to look for the outcome line."
      5: "One block in the pane, one outcome line in the CLI, every time."
    evidence:
      - cli-transcript.txt
      - practice-envelope.json
      - screenshots/
  - id: contributor_path
    prompt: "Persona B (1-3, 5, 6): the documented `uv` setup, `module new`, `module check` and the Persona-A lifecycle work from a clean machine; a broken fixture's JSON failure is readable and repairable; the docs' commands match the observed output."
    scale: [1, 2, 3, 4, 5]
    anchors:
      1: "A documented command did not exist or did not behave as the page says."
      3: "Everything worked, but one output differed from the docs in a way that needed explaining."
      5: "Every documented command ran as written and produced what the page shows; the failure JSON named the rule, file and line."
    evidence:
      - cli-transcript.txt
      - docs-drift.txt
reject_if:
  - "a REQUIRED journey cell is skipped rather than run (D-13: a sign-off can never pass through skips)"
  - "hint, solution or mentorNotes text is present anywhere in a captured page (proposal §5.6, C7)"
  - "a second study session or a second console was created at any point (ADR-0009)"
  - "a drill phase executed without the CLI's `Run this phase now?` consent (proposal §5.5, §8)"
  - "an overdue counter or any count of pending drills was visible (C7)"
  - "either persona needed a facilitator explanation or a retry to complete (design.md §6 sign-off)"
  - "the evidence bundle is missing manifest.json or any file its own inventory names"
---

# Module UAT sign-off rubric, version 2

Loaded by `tests/acceptance/uat/rubric.py` with the `module_rubric_registry.json` registry
beside it: the file's sha256 must match the pinned hash for the `version` above, so an edit
made in place without bumping `version` and registering a new hash is rejected as tampering
(`RubricTamperedError`), never silently accepted.

## The two personas (design.md §6)

**Persona A -- AuDHD learner on a tablet over `--lan`** (viewport 820x1180; acceptance budget
6 min, UAT 12 min): (1) load, no Labs entry and no prerequisite text; (2) `studyloop module add
<scaffold>`, reload, exactly one Labs entry; (3) open it, start one drill inside the single
claimed session; (4) focus and Tab / Shift-Tab / Escape usable; (5) cancel with clear recovery
copy; (6) reload re-attaches with no second session; (7) a fixture missing `kind` gives a
concise prerequisite report and creates nothing; (8) `module remove`, reload, Labs gone. No
overdue counter, hint, solution or mentor notes in the DOM at any step.

**Persona B -- new contributor on a clean machine** (viewport 1440x900; acceptance 8 min, UAT
15 min): (1) the documented `uv` setup; (2) `module new`; (3) `module check`; (4) the Persona-A
lifecycle; (5) break one fixture, read the JSON failure, repair it; (6) the docs' commands and
the observed output agree.

## How a seat grades

Each seat receives the bundle's REDACTED summary plus this rubric and returns one score per
criterion with a citation into the evidence the criterion names. The coordinator arbitrates
into one `ARBITRATION` file beside the private bundle, never inside `releases/`.

## Sign-off

Both personas complete twice without a retry or a facilitator explanation; every assertion
green; no high-severity console or server error; the learner can say where to start and where
to stop without having seen an answer. Any `reject_if` condition fails the run regardless of
the weighted average ("never gate at the point estimate").

Revision 2 (2026-10-05, M2 arbitration): bundle members renamed to what lane U1 ships (`server-log.txt`, `labs-binding.json`, `practice-envelope.json` when a phase ran); the missing-`kind` prompt now describes the shipped contract (add is static; doctor reports; drill refuses before consent). Version 1 is kept, pinned, for runs that already cite it.
