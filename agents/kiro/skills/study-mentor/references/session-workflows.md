# Session Workflows

## Scheduled Study Session

```text
1. Run:
   studyctl status
   studyctl review
   studyctl struggles
   studyctl wins

2. Ask:
   "Energy level 1-10? Tired, wired, or in-between?"

3. Select session type:
   1-3: body double, recall, or one small concept
   4-6: light Socratic review
   7-8: deep Socratic session on weak area
   9-10: new concept or challenge exercise

4. Use shared DB context:
   - recurring struggles
   - wins
   - previous sessions
   - due review
   - parked topics

5. Conduct Socratic session:
   - one question at a time
   - network/data-engineering bridges when useful
   - explicit check for overload
   - metacognitive checkpoints every 3-5 exchanges

6. Record progress:
   studyctl progress "<concept>" -t <topic> -c <confidence>
```

## Spaced Review Session

```text
1. Check what is due:
   studyctl review

2. Pick at most 3 topics.

3. For each topic:
   - ask one recall question
   - ask one transfer/application question
   - ask one "explain it back" question

4. Record confidence:
   studyctl progress "<concept>" -t <topic> -c <confidence>
```

## Body Doubling Session

```text
1. Ask: "What are you working on? How long do you want to go?"
2. Agree the first visible micro-step.
3. Midpoint check:
   "Quick check - still on the same task, or do we need to adjust?"
4. End:
   "What did you accomplish, and what is the first step next time?"
5. Record useful progress or blockers.
```

## Ad-Hoc Question

```text
1. Identify the topic.
2. Check prior context if useful:
   studyctl struggles --days 30
   session-query search "<topic>"
3. Respond using Socratic methodology.
4. Save or record a teaching moment when significant.
```

## Quiz And Flashcard Generation

Use local generation:

```bash
studyctl content generate-cards ~/Obsidian/Personal/Study/<topic-or-course> --course <course-slug>
studyctl web
```

Energy adaptation:

- Energy 1-3: review existing cards only, or body double.
- Energy 4-6: generate only one artefact type if needed.
- Energy 7+: generate and use review artefacts as part of an active Socratic session.

## End-of-Session Protocol

1. Record progress:

```bash
studyctl progress "<concept>" -t <topic> -c <confidence>
```

2. Summarise:
   - what improved
   - what remains unclear
   - parked topics
   - first step next time

3. Suggest review timing based on spaced repetition.
