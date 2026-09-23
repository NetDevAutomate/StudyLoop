# Recording Protocol — when the mentor writes

The learning tier is fed by four **additive writers**. Each appends a record the
learner has agreed to or stated; none reschedules anything. This file is the one
instruction that says *when* each fires. Every harness definition points here,
so the mentor behaves the same on Kiro CLI, Claude Code, Codex, OpenCode, pi and
Grok Build — parity is of the instruction, never of approval: whether a call
prompts is the harness's own setting, and nothing here changes it.

## Trigger table

```yaml
- trigger: teach_back_agreed
  when: "you proposed five rubric scores in one sentence and the learner's next reply accepted them (a yes, or a corrected set they say they accept)"
  writer: record_teachback
  required_ids: [concept, topic, scores, review_type]
  consent: learner_agreed
- trigger: stuck_two_rounds
  when: "two Socratic rounds on the same point without a breakthrough"
  writer: log_struggle
  required_ids: [question]
  consent: learner_stated
- trigger: session_end_concepts
  when: "the session is ending; one call per concept touched, with the status the learner confirmed"
  writer: log_topic
  required_ids: [topic, status]
  consent: learner_confirmed
- trigger: plan_wind_down
  when: "wind-down of a session run against an active study plan; one line on what was learned"
  writer: record_plan_learning
  required_ids: [plan_id, title]
  consent: learner_agreed
```

## The triggers, one line each

- **`teach_back_agreed` → `record_teachback`.** After a teach-back, propose the five scores
  (accuracy, own words, structure, depth, transfer — each 1 to 4) in one sentence. When the
  learner agrees, record them with the review type (`micro`, `structured`, `transfer`, `full`).
  Not agreed, not recorded. A low-energy blank is never scored (teach-back protocol).
- **`stuck_two_rounds` → `log_struggle`.** When the learner has said, in effect, "I'm stuck" for
  two rounds on one point, log the question so it returns for spaced repetition. Say that you did.
- **`session_end_concepts` → `log_topic`.** At wind-down, name each concept touched and the
  status the learner confirms (`learning`, `struggling`, `insight`, `win`, `parked`) — one call each.
- **`plan_wind_down` → `record_plan_learning`.** If the session ran against an active plan, offer
  one line for the plan's learning record; write it when the learner agrees.

## What never fires from this table

- `record_study_progress`, `log_review_outcome`, `record_topic_progress` reschedule a card or
  resolve a backlog topic on an id nothing verifies. They stay learner-initiated, one prompt per
  call, on every harness.
- A turn that matches no trigger writes nothing. Do not "keep the record warm".
- Nothing here reads a transcript or infers a score; the learner's agreement is the signal.

## Saying so

After any write, one short line: *"Recorded: window frame, structured, 15/20."* Then the next
question. Never a paragraph.

If the write does not happen — the tool refuses, the learner declines the harness's approval prompt,
or the database is unavailable — say that in one line (*"Not recorded — the database refused; the
CLI `studyloop teachback …` is the fallback."*) and continue. Never retry silently, never claim a
record that did not land.
