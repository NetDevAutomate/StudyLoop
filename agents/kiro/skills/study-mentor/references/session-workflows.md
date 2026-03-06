# Session Workflows

## Scheduled Study Session

```
1. Run: studyctl status
   → Identify topics with pending changes
   → Sync if needed: studyctl sync --all

2. Run: uv run tutor-progress
   → Identify weakest skills
   → Check last study dates for spaced repetition

3. Ask: "Energy level 1-10? Tired, wired, or in-between?"
   → 1-3: Audio review only (generate/play podcast)
   → 4-6: Light Socratic review of familiar topic
   → 7-8: Deep Socratic session on weak area
   → 9-10: New concept introduction with exercises

4. Select topic based on:
   → Lowest skill score + energy match
   → Spaced repetition schedule (what's due?)
   → Study plan phase (check study plan via studyctl)

5. Query NotebookLM for context:
   notebooklm ask "Summarise key concepts about [topic]" --notebook <id>

6. Conduct Socratic session using audhd-socratic-mentor skill:
   → One question at a time
   → Network→DE bridges
   → AuDHD cognitive support active
   → Metacognitive checkpoints every 3-5 exchanges

7. Record progress:
   uv run tutor-checkpoint code --skill <relevant_skill>

8. Save teaching moment if significant:
   → Write to teaching moments directory (configured in ~/.config/studyctl/config.yaml)
```

## Spaced Review Session

```
1. Check what's due:
   → Query progress DB for topics studied 1/3/7/14/30 days ago
   → Prioritise by: overdue > weak score > high weight

2. For each due topic (max 3 per session):
   a. Pull key concepts from NotebookLM:
      notebooklm ask "What are the 3 most important concepts about [topic]?" --notebook <id>

   b. Quick Socratic quiz (5 min per topic):
      → "Without looking, what's the relationship between [X] and [Y]?"
      → "If you had to explain [concept] using a networking analogy, what would you say?"
      → "What would break if we removed [component] from this pattern?"

   c. Score and record:
      → Confident recall → score up, extend interval
      → Partial recall → same interval, note gaps
      → No recall → score down, schedule for tomorrow

3. Summary:
   → "Reviewed 3 topics. Strong on [X], need to revisit [Y] tomorrow."
```

## Body Doubling Session

```
1. "What are you working on? How long do you want to go?"
2. Set timer mentally
3. Midpoint (halfway): "Quick check — how's it going? Need to adjust?"
   → Keep brief, don't break flow
   → If stuck: offer micro-step suggestion
4. End: "Time's up. What did you accomplish?"
   → Record what was done
   → "What's the first micro-step for next time?"
5. If they want to continue (hyperfocus):
   → "You've been at it [X] hours. Have you eaten/hydrated?"
   → Support continuation with time warnings
```

## Ad-hoc Question

```
1. Identify which topic the question belongs to
2. Query NotebookLM for relevant context:
   notebooklm ask "[question context]" --notebook <topic_id>
3. Respond using audhd-socratic-mentor methodology:
   → Don't answer directly
   → Guide with questions
   → Use network→DE bridge if applicable
4. If concept is significant, save teaching moment
```

## Audio Generation

```
1. Check when audio was last generated for topic
2. If >7 days or >5 new sources since last generation:
   studyctl audio <topic> -i "Focus on [weak areas from progress tracker]. Use networking analogies for [specific concepts]."
3. Wait for generation (10-20 min)
4. Download when ready:
   notebooklm download audio <topic>-overview.mp3
5. Suggest: "New audio overview ready. Listen during commute/walk."
```
