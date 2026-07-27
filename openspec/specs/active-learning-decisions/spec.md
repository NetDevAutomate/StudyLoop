## Purpose

Choose one concrete study action for right now from due reviews, weak
concepts, practice tasks, session continuity, and transfer gaps — weighted
by energy, time budget, modality preference, and interleave mode.  Expose
the decision via `studyloop now`, and provide supporting surfaces:
`studyloop chat-note` (Socratic context packs), `studyloop practice verify`
(attempt recording), `studyloop recap today` (daily synthesis with optional
voice), and `studyloop mastery graph|weak-links` (dependency inspection).

## Requirements

### Requirement: The decision engine produces a ranked plan from multiple candidate sources
`build_now_plan()` (`learning/decision.py`) SHALL gather candidates from
five sources — due spaced-repetition cards (`_due_card_candidates`), due
progress items (`_due_progress_candidates`), struggling/low-score concepts
(`_struggle_candidates`), last-session continuity (`_continuity_candidates`),
and practice-task files (`_practice_candidates`) — then optionally add
transfer/weak-link candidates when `interleave="adaptive"` and energy is
not `"low"`.  It SHALL return a `NowPlan` containing one `primary`
recommendation plus up to two `alternates`, deduped by
`(topic, concept, action_type)`.

#### Scenario: Fresh database with no learning evidence
- **WHEN** all candidate sources return empty lists
- **THEN** `build_now_plan()` returns a `NowPlan` with `starter=True` and
  a single fallback recommendation sourced from the first configured topic

#### Scenario: Multiple candidate sources produce overlapping entries
- **WHEN** the same `(topic, concept, action_type)` tuple appears from both
  `_due_progress_candidates` and `_struggle_candidates`
- **THEN** `_dedupe()` retains only the highest-scored instance

### Requirement: Energy and modality reshape candidate scoring
`_score_candidates()` SHALL apply additive/subtractive adjustments to each
candidate's base score: modality match adds 18 points; low energy penalises
`hands-on`/`visual` by −14 and cross-topic candidates by −28; high energy
boosts `hands-on`/`visual`/`teachback` by +10.  Adaptive interleave mode
further penalises or boosts `visual` candidates depending on energy band.

#### Scenario: Low-energy session requests audio modality
- **WHEN** `energy="low"` and `modality="audio"`
- **THEN** candidates whose `action_type` is `hands-on` or `visual` lose
  14 points, and candidates from a different topic than the last session
  lose an additional 28 points, making continuity-based recall/conversation
  candidates dominate

### Requirement: The CLI exposes the plan with energy, time, modality, interleave, speak, and json flags
`studyloop now` (`cli/_now.py`) SHALL accept `--energy` (low/medium/high,
default medium), `--time` (int minutes, default 25), `--modality`
(recall/conversation/hands-on/visual/audio, default recall),
`--interleave` (off/adaptive, default off), `--json` (output as JSON), and
`--speak` (speak the primary recommendation via `speak_text()`).  The time
input is clamped to `[5, 180]` inside `build_now_plan()`.

#### Scenario: User asks for a quick low-energy recommendation
- **WHEN** `studyloop now --energy low --time 15` is invoked
- **THEN** the returned plan has `energy="low"`, `time_minutes=15`, and
  the primary recommendation's `estimated_minutes` respects the per-action
  floor (5 min for recall/audio, 10 min for other types)

### Requirement: chat-note builds a Socratic context pack scoped to allowed study roots
`build_note_companion_pack()` (`learning/note_companion.py`) SHALL resolve
the note path against `allowed_note_roots()` (obsidian vault, study paths,
content base path) and reject paths outside those roots with a `ValueError`.
It SHALL chunk the note by headings and code fences (limit 8 chunks), build
a mode-specific instruction prompt (recall/diagram/trace/teachback/repair),
and return a `NoteCompanionPack` including the full prompt and a
`suggested_command` for recording evidence.

#### Scenario: Note outside configured roots
- **WHEN** `studyloop chat-note /etc/passwd --mode recall` is invoked
- **THEN** the command raises a `ClickException` wrapping the ValueError
  "Note is outside the configured StudyLoop study/vault roots."

#### Scenario: Teachback mode
- **WHEN** `--mode teachback` is passed
- **THEN** the `suggested_command` in the pack is a `studyloop teachback`
  invocation and the prompt instructs the agent to run a teach-back

### Requirement: practice verify records attempts and updates study progress
`verify_practice_task()` (`learning/practice.py`) SHALL load a
`PracticeDeck` from the JSON path, validate the 1-based task index,
determine verification kind (`command` or `checklist`), check expected
artifacts, and record the result to `practice_attempts` via
`_record_attempt()`.  It SHALL also call `record_progress()` with
confidence `"confident"` on pass or `"struggling"` on fail.  Command
verification requires the `--run-command` flag; without it, a
`PermissionError` is raised.

#### Scenario: Checklist verification with missing artifacts
- **WHEN** a task has `verification.kind = "checklist"`, the user provides
  `--notes "done"`, but one expected artifact file is absent from workdir
- **THEN** `passed` is `False` (notes present but missing artifacts),
  progress is recorded as `"struggling"`, and the attempt row is inserted

#### Scenario: Command verification without --run-command
- **WHEN** `studyloop practice verify deck.json --task 1` is invoked
  without `--run-command` and the task's verification kind is `"command"`
- **THEN** a `PermissionError` is raised with message "Command
  verification requires --run-command."

### Requirement: recap today synthesises a four-field daily summary with optional voice and audio export
`build_daily_recap()` (`learning/recap.py`) SHALL assemble a `DailyRecap`
with fields `win`, `repair_target`, `due_item`, and `next_action` sourced
from `get_wins(days=1)`, `get_struggling_topics(days=7)`,
`spaced_repetition_due()`, and `build_now_plan()` respectively.  The CLI
(`cli/_recap.py`) SHALL accept `--speak` (live TTS via `speak_text()`),
`--audio-file PATH` (export via `synthesize_text_to_file()`), and `--json`.
When all data sources are empty, `has_data` is `False` and the recap
provides safe fallback strings.

#### Scenario: No learning data available
- **WHEN** `studyloop recap today` runs on a fresh install with an empty DB
- **THEN** the recap panel shows a fallback win ("You kept the loop alive
  by checking in"), `has_data` is `False`, and `next_action` is
  `build_now_plan().primary.evidence_command`

#### Scenario: Audio file export
- **WHEN** `studyloop recap today --audio-file recap.wav` is invoked
- **THEN** `synthesize_text_to_file()` (`learning/voice.py`) is called
  with `recap.speakable_text()` and the resolved path; success prints a
  green confirmation, failure prints a yellow warning

### Requirement: mastery graph renders concept dependencies as Mermaid or JSON
`mastery_graph_mermaid()` and `mastery_graph_json()` (`learning/mastery.py`)
SHALL query `concept_dependencies` for the given topic, seed edges from
local markdown (heading paths, wikilinks, tags) and existing
`concept_relations`/`knowledge_bridges` tables if the topic has no edges
yet, then return a Mermaid `flowchart LR` string or a JSON dict with
`nodes`, `edges`, `edge_count_total`, and `limited` flag.

#### Scenario: Topic with no pre-existing edges
- **WHEN** `studyloop mastery graph --topic python` runs and
  `concept_dependencies` has no rows for "python"
- **THEN** `seed_inferred_dependencies("python")` scans configured
  markdown roots for heading adjacency, wikilinks, and tags, inserts
  edges with confidence 0.35–0.50, and the graph renders those seeded
  edges

### Requirement: weak-links surfaces struggling prerequisites that block downstream concepts
`weak_links_for_topic()` (`learning/mastery.py`) SHALL join
`concept_dependencies` edges with `study_progress` rows for the topic,
filter to source concepts whose confidence is `"struggling"` or
`"learning"` or whose `last_teachback_score < 14`, and return them sorted
by severity (struggling first, then by ascending teachback score).

#### Scenario: A concept recorded as struggling feeds two downstream edges
- **WHEN** `study_progress` has concept "list comprehensions" with
  confidence "struggling" and `concept_dependencies` has two edges with
  `source_concept = "list comprehensions"`
- **THEN** `weak_links_for_topic()` returns an entry with
  `concept="list comprehensions"` and `reason` containing "is struggling
  and feeds {target_concept}"

### Requirement: Voice output is optional and never blocks the learning workflow
`speak_text()` (`learning/voice.py`) SHALL locate `study-speak` on PATH
(or `~/.local/bin/study-speak`), invoke it with the text, and return a
boolean.  On failure (binary not found, timeout, non-zero exit) it returns
`False` without raising.  Every CLI caller (`_now.py`, `_chat_note.py`,
`_recap.py`) SHALL print a yellow warning and continue when `speak_text()`
returns `False`.

#### Scenario: study-speak binary not installed
- **WHEN** `studyloop now --speak` runs and `study-speak` is not on PATH
  and not at `~/.local/bin/study-speak`
- **THEN** `speak_text()` returns `False`, the CLI prints "[yellow]Voice
  output was unavailable; continuing without speech.[/yellow]", and the
  recommendation is still displayed normally
