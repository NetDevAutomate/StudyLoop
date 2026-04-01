# Study Setup — Onboarding Agent Skill

## Usage

```
/skill:study-setup
```

Use this skill when a user wants to set up studyctl for the first time, add a new course, or configure their study environment.

## Goal

Walk the user through a conversational, low-pressure onboarding flow. Gather what they're studying, where their materials live, and get them to a working first flashcard review — all without overwhelm.

## MCP Tools Used

- `list_courses` — check what's already configured
- `get_study_context` — pull existing course metadata and progress

## CLI Commands Used

- `studyctl config init` — create initial configuration
- `studyctl content split` — split a PDF into per-chapter markdown
- `studyctl content flashcards` — generate flashcards from chapter content

## Flow

### Step 1: Check Existing State

Call `list_courses` first. If courses already exist, acknowledge them and ask whether the user wants to add a new course or reconfigure an existing one. Do not repeat setup steps for things already done.

### Step 2: Gather Study Context (Conversational)

Ask these questions one at a time — do not dump them all at once:

1. **What are you studying?** Get the course/book name, subject area, and why they're learning it (motivation helps with recall).
2. **Where are your materials?** PDF path, Obsidian vault location, or other sources. Accept drag-and-drop paths.
3. **Do you use NotebookLM?** If yes, ask for their project URL. If no, briefly explain what it offers (audio overviews, AI notebooks) but do not push it.

### Step 3: Initialise Configuration

Run `studyctl config init` with the gathered details. Confirm the config file location and contents with the user before proceeding.

### Step 4: Split Content

If a PDF was provided:
- Run `studyctl content split --pdf <path>` to extract chapters
- Show the user the chapter list and total page count
- Celebrate: "Your book is ready — X chapters extracted"

### Step 5: Demo — First Flashcards

Generate sample flashcards from Chapter 1 using `studyctl content flashcards --course <name> --chapter 1`. Show 3-5 cards as a preview. Ask: "Do these look useful? Want to adjust the style?"

### Step 6: Confirm and Summarise

Print a clear summary of what was set up:
- Course name and chapter count
- Config file location
- Next suggested action (e.g., "Run a study session with /skill:study-generate")

## AuDHD-Friendly Guidelines

- **One thing at a time.** Never present more than one question or action per message.
- **Validate each step.** Confirm success before moving on. If something fails, explain clearly and offer to retry.
- **No jargon without context.** If a CLI flag or concept is non-obvious, explain it in one sentence.
- **Celebrate small wins.** "Chapter split complete — you're ready to study" beats a silent success.
- **Offer escape hatches.** "We can skip NotebookLM setup for now and add it later" — never make optional steps feel mandatory.
- **Keep messages short.** Walls of text cause context-switching fatigue. Prefer 2-4 sentences per response.
