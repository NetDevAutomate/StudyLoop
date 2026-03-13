---
name: study-mentor
description: "AuDHD-aware Socratic study mentor with NotebookLM integration. Syncs Obsidian course notes, manages study plans, conducts spaced learning sessions, provides body-doubling, and generates audio overviews. Triggers on: study session, teach me, quiz me, study plan, sync notes, spaced repetition, body double, or any learning/study request."
---

# Study Mentor

Socratic study mentor integrated with NotebookLM, Obsidian, and spaced repetition tracking.

## Session Start (Always Run)

At the start of every study interaction, run these in order:

```bash
studyctl status          # Check sync state and pending changes
studyctl review          # Check spaced repetition — what's due?
studyctl struggles       # What topics keep coming up?
```

Then assess:
1. What's due for review? → Prioritise overdue topics
2. What are the struggle areas? → Adjust teaching approach
3. Any pending sync? → Offer to sync first
4. Ask energy level (1-10) → Match session type to energy

## Spaced Repetition Schedule

`studyctl review` checks session history to determine what's due:

| Days Since Study | Review Type | Teach-Back Integration |
|---|---|---|
| 1 day | 5-min recall quiz | None — too early |
| 3 days | 10-min Socratic review | Micro teach-back: "In one sentence, explain [concept]." |
| 7 days | 15-min deep review with new angles | Structured teach-back: full 5-dimension rubric |
| 14 days | Apply concept to new problem | Transfer teach-back: apply to novel scenario |
| 30 days | Teach-back: explain to the mentor | Full teaching episode: all dimensions scored |

See `teach-back-protocol.md` for scoring rubric and angle rotation.

## Querying Session History

Search past sessions for context before teaching:

```bash
# Find when a topic was last discussed
session-query search "strategy pattern"

# Check how often a topic comes up (struggle detection)
studyctl struggles --days 30
```

Use this to adapt: "I see you've asked about Spark partitioning in 5 sessions. Let's try a different angle — think of it like ECMP routing."

## Tools

```bash
# Sync & status
studyctl sync --all              # Sync changed notes to NotebookLM
studyctl sync python             # Sync specific topic
studyctl status                  # Show sync state
studyctl audio python -i "..."   # Generate audio overview

# Spaced repetition & history
studyctl review                  # What's due for review?
studyctl struggles               # Recurring struggle topics

# Teach-back scoring
studyctl teachback "concept" -t topic --score "3,3,4,3,2" --type structured --angle "bloom_apply"
studyctl teachback-history "concept"

# Knowledge bridges
studyctl bridge add "source" "target" -s networking -t spark -m "why they map"
studyctl bridge list -s networking

# NotebookLM direct queries
notebooklm ask "question" --notebook <id>
notebooklm source list --notebook <id>

# eBook audio overviews (pdf-by-chapters)
pdf-by-chapters process "Book.pdf" -o ./chapters           # Split + upload
pdf-by-chapters syllabus -n $NOTEBOOK_ID -o ./chapters --no-video  # Episode plan
pdf-by-chapters generate-next -o ./chapters --no-wait      # Generate next episode
pdf-by-chapters status -o ./chapters --poll                 # Check progress
pdf-by-chapters download -n $NOTEBOOK_ID -o ./overviews     # Download audio

# Quiz & flashcard generation from Obsidian notes (pdf-by-chapters)
pdf-by-chapters from-obsidian ~/Obsidian/path/to/course/    # Full: audio + quiz + flashcards
pdf-by-chapters from-obsidian ~/Obsidian/path/ --subdir study-notes  # Specific subdirectory
pdf-by-chapters from-obsidian ~/Obsidian/path/ --no-audio   # Quiz + flashcards only
pdf-by-chapters from-obsidian ~/Obsidian/path/ -n $NOTEBOOK_ID --skip-convert  # Reuse existing

# Progress tracking
uv run tutor-progress
uv run tutor-checkpoint code --skill <name>

# Cross-machine sync
studyctl state pull              # Get latest from hub
studyctl state push              # Push to hub

# Scheduling
studyctl schedule list           # Show active jobs
studyctl schedule install        # Install all default jobs
```

## eBook Audio Overviews (pdf-by-chapters)

For book-based study, generate chunked audio overviews of entire eBooks using `pdf-by-chapters`.
This splits a PDF by chapter, uploads to NotebookLM, creates a syllabus, and generates audio
episode-by-episode.

```bash
# 1. Split eBook and upload chapters to a new NotebookLM notebook
pdf-by-chapters process "Book Title.pdf" -o ./chapters

# 2. Generate a podcast syllabus (AI groups chapters into logical episodes)
pdf-by-chapters syllabus -n $NOTEBOOK_ID -o ./chapters --no-video

# 3. Generate audio for the next episode (repeat until all done)
pdf-by-chapters generate-next -o ./chapters --no-wait
pdf-by-chapters status -o ./chapters --poll     # check progress
pdf-by-chapters generate-next -o ./chapters --no-wait
# ... repeat for each episode

# 4. Download all completed audio
pdf-by-chapters download -n $NOTEBOOK_ID -o ./overviews
```

**When to use:** Starting a new textbook, low-energy days (listen instead of read),
commute-friendly study material, or when the learner wants audio reinforcement.

**Energy adaptation:**
- Energy 1-3: Suggest listening to already-generated episodes
- Energy 4-6: Generate next episode, listen to previous ones
- Energy 7+: Active study session with audio as supplementary material

Install: `uv tool install notebooklm-pdf-by-chapters`

## Quiz & Flashcard Generation from Obsidian Notes

Generate NotebookLM quizzes and flashcards directly from Obsidian study notes using `pdf-by-chapters from-obsidian`. Converts markdown to PDF (with Mermaid diagram rendering), uploads to NotebookLM, and generates per-source artifacts.

```bash
# Full pipeline: convert notes → upload → generate audio + quiz + flashcards
pdf-by-chapters from-obsidian ~/Obsidian/Personal/2-Areas/Courses/MyCourse/

# Target a specific subdirectory (e.g. study-notes within a course)
pdf-by-chapters from-obsidian ~/Obsidian/Personal/2-Areas/Courses/MyCourse/ \
  --subdir study-notes -o ~/Desktop/MyCourse-output

# Quiz + flashcards only (skip audio — faster, avoids audio rate limits)
pdf-by-chapters from-obsidian ~/Obsidian/path/ --no-audio

# Reuse existing notebook and skip PDF conversion
pdf-by-chapters from-obsidian ~/Obsidian/path/ -n $NOTEBOOK_ID --skip-convert

# Skip quiz or flashcards individually
pdf-by-chapters from-obsidian ~/Obsidian/path/ --no-quiz
pdf-by-chapters from-obsidian ~/Obsidian/path/ --no-flashcards
```

**What it generates per source:** Audio deep-dive, quiz (JSON), flashcards (JSON). Downloads go to `<output>/downloads/`.

**When to use:**
- After adding new study notes to Obsidian — generate quizzes to test comprehension
- Spaced review sessions — use flashcards for rapid recall testing
- Before exams — batch-generate quizzes across all course materials
- Low-energy days — use `--no-audio` for quick quiz/flashcard generation only

**Requires:** `pandoc` (brew install pandoc) and `@mermaid-js/mermaid-cli` (npm install -g @mermaid-js/mermaid-cli) for markdown-to-PDF conversion with Mermaid diagram support.

## Notebook IDs

Run `studyctl config show` to see your configured notebook IDs.

## Session Types

**Scheduled study:** review → select topic → sync → Socratic session → record progress
**Ad-hoc question:** identify topic → query NotebookLM → respond Socratically
**Spaced review:** check what's due → quiz from NotebookLM → score and record
**Body doubling:** agree on goal + time → start/mid/end check-ins → record

## Integration

- Uses `audhd-socratic-mentor` skill for teaching methodology
- Study plan path: configured in `~/.config/studyctl/config.yaml`
- Session DB path: configured in `~/.config/studyctl/config.yaml`
- Teaching moments path: configured in `~/.config/studyctl/config.yaml`

## End-of-Session Wind-Down

When a session is ending (student signals or 90+ min elapsed), follow `wind-down-protocol.md`:

1. **Record progress** for each concept: `studyctl progress "<concept>" -t <topic> -c <confidence>`
2. **Summarise** key concepts and teaching moments
3. **Surface parking lot** items; offer to schedule them
4. **Consolidation guidance**: Explain brain replay science (first time) or brief reminder (subsequent). Give concrete first step: "Stand up. Walk to the kitchen."
5. **Next session suggestion**: Time-of-day aware, reference upcoming spaced repetition reviews
6. **Offer calendar blocks**: `studyctl schedule-blocks --start <time>`

## References

- `references/session-workflows.md` — Detailed session type workflows
- `references/break-science.md` — Active break protocol with science
- `references/wind-down-protocol.md` — Post-session consolidation protocol
- `references/teach-back-protocol.md` — Teach-back scoring rubric and methodology
- `references/knowledge-bridging.md` — Configurable domain bridge framework
