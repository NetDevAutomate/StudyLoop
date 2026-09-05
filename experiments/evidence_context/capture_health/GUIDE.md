# Stage 4: knowing whether history was captured

## The question and the misleading shortcut

An agent searches history and finds nothing. This could mean the topic was never
discussed, the query missed it, an export failed, or the relevant source was never
configured. Empty retrieval alone cannot distinguish those explanations.

This stage tests the capture-health evidence we would need. It does not attach
health to the earlier retrieval packs yet and does not probe installed harnesses.

## Run it independently

From the experimental worktree root:

```sh
uv run python -m experiments.evidence_context.capture_health --output /tmp/evidence-stage-4
uv run --group dev pytest experiments/evidence_context/tests/test_capture_health.py -q
```

Use a new output directory. The demo creates capture.db, a synthetic source file,
and report.json. No previous stage output is needed and no model calls are made.
All messages and configuration states are synthetic.

Open report.json and compare these scenarios:

| Scenario | Expected observation | Meaning |
|---|---|---|
| Installed, never captured | no_successful_capture | Hook configuration is not execution evidence. |
| Successful capture | recent_capture_observed | One completed import is observed; history completeness is still not_established. |
| Failed after success | parse_failed plus retained last_success | A later failure cannot be hidden by an earlier success. |
| Disabled hook | hook_registered_missing | Manual import success does not establish automatic capture. |
| Delayed capture | capture_stale | The configured freshness threshold is exceeded. |
| Unknown coverage | repair_coverage_unknown | We have not established whether backfill missed history. |

Later scenarios deliberately retain the earlier parse failure. These health
conditions can coexist, so the report exposes a list of issues rather than hiding
all but the highest-priority one.

## Why these tables?

`records` stores actual imported synthetic rows keyed by source and ID.
`attempts` stores import outcomes, timestamps, counts and bounded error codes.
Reports read the attempt history rather than guessing health from a file's age or
the presence of a hook configuration file.

Separating records from attempt metadata lets a failed import preserve the last
successful data while reporting the failure. The importer validates the whole
file before writing any record. Record writes and success reporting share one
transaction. A batch with a bad row cannot leave a partly imported dataset labelled
successful. SQLite is sufficient for this experiment; another engine would still
need the same transaction and observation semantics.

This is an incremental upsert importer. An empty file does not delete earlier
rows; it records an observed zero-row import. It is not a replacement snapshot,
and does not implement source deletion or replace stage 3's lifecycle rules.

## Why not one green/red status?

We retain the underlying facts: source detection, skill and hook configuration,
last attempt, last success, capture age, parse failures and known/unknown repair
gaps. A summary status is useful for scanning, but an agent needs the details to
explain what is missing and why it should qualify its answer.

The successful state is named `recent_capture_observed`, not `history_complete`.
Completeness needs an independently enumerated set of expected sources and a
comparison with captured coverage. This lab cannot provide that proof.

The freshness threshold is supplied by the caller. Two hours in the demo is a
fixture value, not a recommended universal policy. A quiet project and an active
coding session have different expectations; last import age is not source-event
lag. Future telemetry should include the newest discoverable source event and
capture watermarks before claiming that all available events are imported.

## Why error codes instead of exception text?

Parse exceptions can include source content or filesystem details. Health reports
need actionable categories, not transcript excerpts. This lab records parse_failed
or source_unreadable and checks that a synthetic private marker does not enter the
report. Caller-supplied source labels also need safe handling in a real integration.

## What is actually exercised?

Tests parse real temporary files and write actual SQLite rows. They cover malformed
batches, unreadable files, valid empty inputs, repeat imports, source isolation,
unknown configuration, disabled hooks, stale capture, future clocks and retained
prior success. Configuration detection and repair-gap counts are caller fixtures;
these tests do not validate real installation or backfill discovery.

Other limits: no automatic retries, no scheduler, no production harness parser,
no machine authentication, no privacy policy engine, no bounded event retention,
and no true completeness census. No database performance measurements are made.
The health adapter must not bypass the lifecycle deletion policy if integrated
later. This stage is separated precisely so those integrations are explicit tests.

## Small learning exercise

Before running the demo, predict whether a successful manual import should make a
missing hook warning disappear. Then compare your answer with disabled_hook.
A useful optional 5–10 line exercise is a display function that combines last_success
and issues into an agent-facing explanation while avoiding a claim of completeness.
Keep the underlying facts in the output so the summary cannot conceal uncertainty.

## Connection to the larger decision

This stage measures capture observability, not retrieval usefulness. It adds another
reason to defer claims about an optimal engine: accurate context requires evidence
about missing data as well as the data itself. Read the stage-4 council record for
the coordinator's next-step decision after review of all stages.

## Review outcomes

[COUNCIL-DECISION.md](COUNCIL-DECISION.md) records all three reviewers' advice,
accepted fixes, rejected assumptions and the changed next-stage order. Post-review
coverage adds reopening persisted health, UTF-8 handling, timestamp ordering, source
isolation, incremental empty imports, duplicate IDs and actual journal permissions.
The full suite now has 98 passing tests. Completed-attempt logging does not detect
a process crash before its outcome is recorded; durable start/completion telemetry
is a future integration requirement. The lab assumes sequential capture calls.
